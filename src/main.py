from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tomllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
UA = "ai-news-daily/1.0 (+GitHub Actions)"
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Item:
    title: str
    link: str
    summary: str
    published: datetime
    source: str
    trust: int
    topic_key: str = ""
    topic_label: str = ""
    impact: str = ""
    score: int = 0


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
        kept = []
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
            if k.lower().startswith("utm_") or k.lower() in {"gclid", "fbclid", "ref", "source"}:
                continue
            kept.append((k, v))
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urllib.parse.urlencode(kept), "")
        )
    except Exception:
        return url


def title_core(title: str) -> str:
    # Google News 常把发布方附在标题末尾，例如 "Title - Reuters"。
    # 去掉尾部发布方后再做事件去重，避免同一事件被多家媒体重复推送。
    parts = re.split(r"\s+-\s+", title.strip())
    return parts[0] if parts else title


def title_key(title: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", title_core(title).lower())


def parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def text_of(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext())


def parse_feed_bytes(data: bytes, source: str, trust: int) -> list[Item]:
    root = ET.fromstring(data)
    items: list[Item] = []

    for node in root.findall("./channel/item"):
        title = clean_text(text_of(node.find("title")))
        link = canonical_url(clean_text(text_of(node.find("link"))))
        summary = clean_text(text_of(node.find("description")))
        published = parse_datetime(text_of(node.find("pubDate")))
        if title and link and published:
            items.append(Item(title, link, summary, published, source, trust))

    for node in root.findall(f"./{ATOM}entry"):
        title = clean_text(text_of(node.find(f"{ATOM}title")))
        link = ""
        for link_node in node.findall(f"{ATOM}link"):
            rel = link_node.attrib.get("rel", "alternate")
            href = link_node.attrib.get("href", "")
            if href and rel in {"alternate", ""}:
                link = canonical_url(href)
                break
        if not link:
            first = node.find(f"{ATOM}link")
            if first is not None:
                link = canonical_url(first.attrib.get("href", ""))
        summary = clean_text(text_of(node.find(f"{ATOM}summary")) or text_of(node.find(f"{ATOM}content")))
        published = parse_datetime(text_of(node.find(f"{ATOM}published")) or text_of(node.find(f"{ATOM}updated")))
        if title and link and published:
            items.append(Item(title, link, summary, published, source, trust))

    return items


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def google_news_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote_plus(query)
        + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


def collect(sources_cfg: dict[str, Any]) -> tuple[list[Item], list[str]]:
    items: list[Item] = []
    errors: list[str] = []
    for src in sources_cfg.get("sources", []):
        name = str(src.get("name", "unknown"))
        trust = int(src.get("trust", 1))
        try:
            if src.get("type") == "google_news":
                url = google_news_url(str(src["query"]))
            elif src.get("type") == "rss":
                url = str(src["url"])
            else:
                raise ValueError(f"unsupported source type: {src.get('type')}")
            items.extend(parse_feed_bytes(http_get(url), name, trust))
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return items, errors


def phrase_hits(text: str, phrases: list[Any]) -> int:
    return sum(1 for phrase in phrases if str(phrase).lower() in text)


def score_item(item: Item, topics_cfg: dict[str, Any]) -> Item | None:
    settings = topics_cfg.get("settings", {})
    text = f"{item.title} {item.summary}".lower()
    title_lower = item.title.lower()

    # 1) 明确垃圾/商业/无关类型直接剔除
    if phrase_hits(text, settings.get("negative_keywords", [])):
        return None

    # 2) 教程、盘点、观点、传闻等编辑型内容默认剔除
    if phrase_hits(title_lower, settings.get("editorial_phrases", [])):
        return None

    change_hits = phrase_hits(text, settings.get("change_signals", []))
    require_change = bool(settings.get("require_change_signal", True))

    best: tuple[int, str, dict[str, Any]] | None = None
    for key, topic in topics_cfg.get("topics", {}).items():
        keywords = [str(x).lower() for x in topic.get("keywords", [])]
        topic_hits = sum(1 for k in keywords if k and k in text)

        # Google News 的摘要可能混入站点标签，不能让摘要里的孤立品牌词决定主题身份。
        # 普通新闻优先用标题识别实体；官方 Release 可把 source 名称一起作为身份依据。
        is_official_release = item.trust >= 5 and "release" in item.source.lower()
        identity_text = (
            f"{item.title} {item.source}".lower()
            if is_official_release
            else title_lower
        )

        strong_hits = phrase_hits(identity_text, topic.get("strong_keywords", []))
        ambiguous_hits = phrase_hits(identity_text, topic.get("ambiguous_keywords", []))
        context_hits = phrase_hits(text, topic.get("context_keywords", []))
        exclude_hits = phrase_hits(text, topic.get("exclude_keywords", []))

        has_disambiguation_rules = bool(
            topic.get("strong_keywords") or topic.get("ambiguous_keywords")
        )
        if has_disambiguation_rules:
            # 精确产品/官方锚点可直接确认实体。
            # 歧义词必须同时处在正确 AI/产品语境中，并且不能撞入明显的无关领域。
            identity_ok = (
                strong_hits > 0
                or (
                    ambiguous_hits > 0
                    and context_hits > 0
                    and exclude_hits == 0
                )
            )
            if not identity_ok:
                continue
        elif topic_hits == 0:
            continue

        direct_hits = strong_hits or phrase_hits(identity_text, topic.get("direct_keywords", []))
        impact_hits = phrase_hits(text, topic.get("impact_keywords", []))

        # 官方 Release 源本身就代表真实变化；聚合/媒体内容必须出现明确变化信号。
        if require_change and change_hits == 0 and not is_official_release:
            continue

        # 只相关还不够：必须能指向具体工作流影响。
        # 精确产品锚点/官方 Release 可放行；歧义词路线必须命中具体影响点。
        if impact_hits == 0 and strong_hits == 0 and not is_official_release:
            continue

        base = int(topic.get("weight", 1))
        score = base + item.trust

        # 高可信官方/主流发布方加权。Google News 常把发布方名称放在标题尾部。
        preferred_publishers = topics_cfg.get("source_quality", {}).get("preferred_publishers", [])
        if phrase_hits(text, preferred_publishers):
            score += 2
        score += min(topic_hits, 3)
        score += min(change_hits, 3) * 2
        score += min(impact_hits, 4) * 2
        score += min(int(direct_hits), 2)
        score += min(strong_hits, 2) * 2
        if ambiguous_hits and context_hits:
            score += 1

        if any(k in title_lower for k in keywords):
            score += 2
        if change_hits and phrase_hits(title_lower, settings.get("change_signals", [])):
            score += 2

        # 评测/上手/对比并非完全无价值，但只有在变化信号很强时才保留。
        low_value_hits = phrase_hits(title_lower, settings.get("low_value_phrases", []))
        if low_value_hits:
            score -= 3 * low_value_hits

        candidate = (score, key, topic)
        if best is None or candidate[0] > best[0]:
            best = candidate

    if not best:
        return None

    score, key, topic = best
    item.score = score
    item.topic_key = key
    item.topic_label = str(topic.get("label", key))
    item.impact = str(topic.get("impact", ""))
    return item


def dedupe(items: list[Item]) -> list[Item]:
    result: list[Item] = []
    seen_urls: set[str] = set()
    seen_keys: list[str] = []
    for item in sorted(items, key=lambda x: (x.score, x.published), reverse=True):
        if item.link in seen_urls:
            continue
        key = title_key(item.title)
        if not key:
            continue
        if any(key == old or SequenceMatcher(None, key, old).ratio() >= 0.84 for old in seen_keys):
            continue
        seen_urls.add(item.link)
        seen_keys.append(key)
        result.append(item)
    return result


def select(items: list[Item], topics_cfg: dict[str, Any], now: datetime | None = None) -> list[Item]:
    settings = topics_cfg.get("settings", {})
    lookback_hours = int(settings.get("lookback_hours", 30))
    min_score = int(settings.get("min_score", 13))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)

    scored: list[Item] = []
    for item in items:
        if item.published < cutoff or item.published > now + timedelta(hours=1):
            continue
        candidate = score_item(item, topics_cfg)
        if candidate and candidate.score >= min_score:
            scored.append(candidate)

    deduped = dedupe(scored)
    selected: list[Item] = []
    for key, topic in topics_cfg.get("topics", {}).items():
        quota = int(topic.get("max_items", 3))
        group = [item for item in deduped if item.topic_key == key][:quota]
        selected.extend(group)
    return selected


def short_summary(text: str, limit: int = 120) -> str:
    text = clean_text(text)
    if not text:
        return ""
    for sep in ("。", ". ", "；", "; "):
        if sep in text:
            text = text.split(sep, 1)[0] + ("。" if sep == "。" else "")
            break
    return text[:limit] + ("…" if len(text) > limit else "")


def report_payload(items: list[Item], errors: list[str], topics_cfg: dict[str, Any]) -> dict[str, Any]:
    settings = topics_cfg.get("settings", {})
    tz = ZoneInfo(str(settings.get("timezone", "Asia/Shanghai")))
    now_local = datetime.now(timezone.utc).astimezone(tz)
    title = f"{now_local:%Y-%m-%d} {settings.get('title', 'AI 情报日报')}"
    elements: list[dict[str, Any]] = []

    if not items:
        elements.append({"tag": "markdown", "content": "✅ **今日监控完成：未发现达到推送阈值的重要更新。**"})
    else:
        elements.append({"tag": "markdown", "content": f"今日共筛选出 **{len(items)}** 条高价值更新，按分类配额展示。"})
        icons = {
            "seedance_video": "🎬",
            "subtitle_audio": "📝",
            "editing_automation": "✂️",
            "short_drama": "📺",
            "image_generation": "🖼️",
            "foundation_models": "🤖",
            "github_tools": "🛠️",
        }
        first_group = True
        for key, topic in topics_cfg.get("topics", {}).items():
            group = [item for item in items if item.topic_key == key]
            if not group:
                continue
            if not first_group:
                elements.append({"tag": "hr"})
            first_group = False
            quota = int(topic.get("max_items", 3))
            label = str(topic.get("label", key))
            icon = icons.get(key, "📌")
            elements.append({
                "tag": "markdown",
                "content": f"### {icon} {label}（{len(group)}/{quota}）",
            })
            for idx, item in enumerate(group, 1):
                stars = "★" * min(5, max(1, item.score // 2))
                summary = short_summary(item.summary)
                body = (
                    f"**{idx}. [{item.title}]({item.link})**\n"
                    f"重要度：{stars}｜来源：{item.source}\n"
                )
                if summary:
                    body += f"发生了什么：{summary}\n"
                body += f"与你有关：{item.impact}"
                elements.append({"tag": "markdown", "content": body})

    if errors:
        compact = "\n".join(f"- {e[:160]}" for e in errors[:5])
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"⚠️ 部分来源抓取失败（不影响其余来源）：\n{compact}"})

    return {
        "msg_type": "interactive",
        "card": {
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
            "elements": elements,
        },
    }


def send_feishu(webhook: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"User-Agent": UA, "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    code = data.get("code", data.get("StatusCode", 0))
    if code not in (0, "0", None):
        raise RuntimeError(f"Feishu webhook rejected payload: {data}")


def save_debug(items: list[Item], errors: list[str]) -> None:
    out = ROOT / "data" / "last_debug.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
        "items": [
            {
                "title": x.title,
                "link": x.link,
                "source": x.source,
                "published": x.published.isoformat(),
                "topic": x.topic_label,
                "score": x.score,
            }
            for x in items
        ],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不发送飞书")
    args = parser.parse_args()
    topics_cfg = load_toml(ROOT / "config" / "topics.toml")
    sources_cfg = load_toml(ROOT / "config" / "sources.toml")
    raw, errors = collect(sources_cfg)
    selected = select(raw, topics_cfg)
    save_debug(selected, errors)
    payload = report_payload(selected, errors, topics_cfg)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("ERROR: FEISHU_WEBHOOK is not configured", file=sys.stderr)
        return 2
    send_feishu(webhook, payload)
    print(f"sent {len(selected)} items; source_errors={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
