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
STATE_DIR = ROOT / "data" / "state"
HISTORY_FILE = STATE_DIR / "history.json"
DEBUG_FILE = ROOT / "data" / "last_debug.json"
DELIVERY_FILE = STATE_DIR / "last_delivery.json"


@dataclass
class Item:
    title: str
    link: str
    summary: str
    published: datetime
    source: str
    trust: int
    official: bool = False
    topic_key: str = ""
    topic_label: str = ""
    impact: str = ""
    score: int = 0
    product_key: str = ""
    event_tags: tuple[str, ...] = ()


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


def parse_feed_bytes(data: bytes, source: str, trust: int, official: bool = False) -> list[Item]:
    root = ET.fromstring(data)
    items: list[Item] = []

    for node in root.findall("./channel/item"):
        title = clean_text(text_of(node.find("title")))
        link = canonical_url(clean_text(text_of(node.find("link"))))
        summary = clean_text(text_of(node.find("description")))
        published = parse_datetime(text_of(node.find("pubDate")))
        if title and link and published:
            items.append(Item(title, link, summary, published, source, trust, official=official))

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
            items.append(Item(title, link, summary, published, source, trust, official=official))

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
        official = bool(src.get("official", False))
        try:
            if src.get("type") == "google_news":
                url = google_news_url(str(src["query"]))
            elif src.get("type") == "rss":
                url = str(src["url"])
            else:
                raise ValueError(f"unsupported source type: {src.get('type')}")
            items.extend(parse_feed_bytes(http_get(url), name, trust, official=official))
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return items, errors


def phrase_hits(text: str, phrases: list[Any]) -> int:
    return sum(1 for phrase in phrases if str(phrase).lower() in text)



def normalize_product_key(text: str) -> str:
    text = clean_text(text).lower()

    patterns = [
        (r"\bgpt[-\s]?(\d+(?:\.\d+)*)\s*(sol|luna|astra)?", "gpt"),
        (r"\bclaude\s+([a-z]+)?\s*(\d+(?:\.\d+)*)?", "claude"),
        (r"\bgemini\s+([a-z]+)?\s*(\d+(?:\.\d+)*)?", "gemini"),
        (r"\bseedance\s*(\d+(?:\.\d+)*)?", "seedance"),
        (r"\bveo\s*(\d+(?:\.\d+)*)?", "veo"),
        (r"\bkling\s*(\d+(?:\.\d+)*)?", "kling"),
        (r"\bflux[.\s-]*(\d+(?:\.\d+)*)?", "flux"),
        (r"\bimagen\s*(\d+(?:\.\d+)*)?", "imagen"),
        (r"\bindex[-\s]?(translate|echo|homura)\b", "index"),
        (r"\blarge[-\s]?v(\d+)(?:[-\s]?(turbo))?", "whisper-large-v"),
    ]
    for pattern, prefix in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        parts = [prefix]
        for g in m.groups():
            if g:
                parts.append(re.sub(r"[^0-9a-z]+", "", g.lower()))
        return "-".join(parts)

    fixed = [
        "faster-whisper", "silero vad", "silero-vad", "midjourney",
        "capcut", "剪映", "红果短剧", "chatgpt", "codex",
    ]
    for name in fixed:
        if name in text:
            return re.sub(r"\s+", "-", name.lower())

    return ""


def event_tags_for_text(text: str) -> tuple[str, ...]:
    text = text.lower()
    groups = {
        "commercial": [
            "pricing", "price", "cost", "api pricing", "价格", "定价", "降价", "涨价", "成本",
        ],
        "api": [" api", "api ", "接口", "sdk"],
        "capability": [
            "now supports", "adds support", "新增", "支持", "feature", "能力",
            "context window", "上下文", "tool use", "工具调用",
        ],
        "quality": [
            "accuracy", "benchmark", "quality", "wer", "准确率", "跑分", "质量", "错误率",
        ],
        "performance": [
            "speed", "faster", "latency", "throughput", "速度", "延迟", "吞吐", "显存", "memory",
        ],
        "availability": [
            "rollout", "available", "开放", "全量", "上线", "可用", "所有用户",
        ],
        "deprecation": ["deprecated", "deprecation", "sunset", "弃用", "下线"],
        "quantization": ["gguf", "fp8", "fp4", "quantized", "量化"],
        "release": [
            "release", "released", "launch", "launched", "推出", "发布", "新模型",
        ],
    }
    found = []
    for tag, phrases in groups.items():
        if any(p in text for p in phrases):
            found.append(tag)
    return tuple(sorted(found))


def is_media_rehash(item: Item) -> bool:
    if item.official:
        return False
    title = item.title.lower()
    text = f"{item.title} {item.summary}".lower()
    tags = set(event_tags_for_text(text))
    launch_words = [
        "release", "released", "launch", "launched", "推出", "发布", "上线",
    ]
    has_launch = any(x in title for x in launch_words)
    # 媒体稿只重复“发布/推出”，却没有新的商业、能力、质量、性能、弃用、
    # 量化等具体变化时，视为旧闻翻炒，不把文章发布时间当成事件发布时间。
    material = tags - {"release", "availability"}
    return has_launch and not material


def is_commentary_only(item: Item) -> bool:
    if item.official:
        return False
    title = item.title.lower()
    commentary = [
        "媒体：", "媒体:", "别被", "繁荣", "亏损", "热议", "观察",
        "行业观察", "焦虑", "泡沫", "真相", "背后",
    ]
    concrete = [
        "政策", "新规", "规则调整", "审核", "分成调整", "上线新功能",
        "api", "版本", "新增支持", "开放", "下线", "copyright", "monetization policy",
    ]
    return any(x in title for x in commentary) and not any(x in title for x in concrete)


def same_product_event(a: Item, b: Item) -> bool:
    if not a.product_key or not b.product_key or a.product_key != b.product_key:
        return False
    at = set(a.event_tags)
    bt = set(b.event_tags)
    # 同一产品同一天默认只保留一个事件；若两条都是明确且互不相交的
    # 实质变化，可由后续 product quota 层决定是否允许第二条。
    if at & bt:
        return True
    if not at or not bt:
        return True
    return False


def importance_stars(score: int) -> str:
    if score >= 20:
        return "★★★★★"
    if score >= 16:
        return "★★★★"
    if score >= 13:
        return "★★★"
    if score >= 9:
        return "★★"
    return "★"


def build_impact_reason(item: Item, topic: dict[str, Any]) -> str:
    text = f"{item.title} {item.summary}".lower()
    reasons: list[str] = []
    for rule in topic.get("impact_rules", []):
        if phrase_hits(text, rule.get("keywords", [])):
            reason = str(rule.get("reason", "")).strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        if len(reasons) >= 2:
            break
    if reasons:
        return "；".join(x.rstrip("。") for x in reasons) + "。"
    return str(topic.get("impact", ""))


def novelty_signature(item: Item, settings: dict[str, Any]) -> str:
    text = f"{item.title} {item.summary}".lower()
    version_tokens = re.findall(r"\bv?\d+(?:\.\d+){1,3}\b", text)
    terms = [
        str(term).lower()
        for term in settings.get(
            "novelty_terms",
            [
                "api", "pricing", "price", "deprecated", "deprecation", "new model",
                "benchmark", "accuracy", "now supports", "adds support", "gguf",
                "fp8", "fp4", "量化", "价格", "弃用", "准确率", "新增支持",
            ],
        )
        if str(term).lower() in text
    ]
    return "|".join(sorted(set(version_tokens + terms)))


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def history_duplicate(
    item: Item,
    history: list[dict[str, Any]],
    settings: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    current_url = canonical_url(item.link)
    current_key = title_key(item.title)
    current_sig = novelty_signature(item, settings)
    current_product = item.product_key or normalize_product_key(f"{item.title} {item.summary}")
    current_tags = set(item.event_tags or event_tags_for_text(f"{item.title} {item.summary}"))
    for old in history:
        old_url = canonical_url(str(old.get("link", "")))
        if current_url and old_url and current_url == old_url:
            return True, old
        old_product = str(old.get("product_key", ""))
        old_tags = set(old.get("event_tags", []))
        if current_product and old_product == current_product:
            # 同产品同类变化在历史窗口内视为旧事件；只有出现新的实质变化类型才允许再推。
            meaningful_current = current_tags - {"release", "availability"}
            meaningful_old = old_tags - {"release", "availability"}
            if meaningful_current and meaningful_old and meaningful_current & meaningful_old:
                return True, old
            if not meaningful_current and not meaningful_old:
                return True, old

        old_key = str(old.get("title_key", ""))
        if not current_key or not old_key:
            continue
        similarity = SequenceMatcher(None, current_key, old_key).ratio()
        if similarity >= 0.84:
            old_sig = str(old.get("novelty_signature", ""))
            if current_sig == old_sig:
                return True, old
    return False, None


def save_history(
    history: list[dict[str, Any]],
    selected: list[Item],
    topics_cfg: dict[str, Any],
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    settings = topics_cfg.get("settings", {})
    keep_days = int(settings.get("history_days", 14))
    cutoff = now - timedelta(days=keep_days)
    kept: list[dict[str, Any]] = []
    for entry in history:
        try:
            pushed_at = parse_datetime(str(entry.get("pushed_at", "")))
        except Exception:
            pushed_at = None
        if pushed_at and pushed_at >= cutoff:
            kept.append(entry)

    for item in selected:
        kept.append(
            {
                "title": item.title,
                "title_key": title_key(item.title),
                "link": canonical_url(item.link),
                "topic": item.topic_key,
                "score": item.score,
                "novelty_signature": novelty_signature(item, settings),
                "product_key": item.product_key,
                "event_tags": list(item.event_tags),
                "pushed_at": now.isoformat(),
            }
        )

    # 防止极端情况下状态文件无限增长。
    kept = kept[-500:]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(kept, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def delivery_local_date(topics_cfg: dict[str, Any], now: datetime | None = None) -> str:
    settings = topics_cfg.get("settings", {})
    tz = ZoneInfo(str(settings.get("timezone", "Asia/Shanghai")))
    now = now or datetime.now(timezone.utc)
    return now.astimezone(tz).date().isoformat()


def load_last_delivery() -> dict[str, Any]:
    if not DELIVERY_FILE.exists():
        return {}
    try:
        data = json.loads(DELIVERY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def already_delivered_today(
    topics_cfg: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    state = load_last_delivery()
    return state.get("local_date") == delivery_local_date(topics_cfg, now=now)


def save_last_delivery(
    selected: list[Item],
    errors: list[str],
    topics_cfg: dict[str, Any],
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "local_date": delivery_local_date(topics_cfg, now=now),
        "sent_at": now.isoformat(),
        "selected_count": len(selected),
        "source_errors": len(errors),
    }
    DELIVERY_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def score_item(item: Item, topics_cfg: dict[str, Any], debug: dict[str, Any] | None = None) -> Item | None:
    settings = topics_cfg.get("settings", {})
    text = f"{item.title} {item.summary}".lower()
    title_lower = item.title.lower()
    item.product_key = normalize_product_key(text)
    item.event_tags = event_tags_for_text(text)

    if debug is not None:
        debug.update({"title": item.title, "source": item.source, "status": "evaluating"})

    # 1) 明确垃圾/商业/无关类型直接剔除
    if phrase_hits(text, settings.get("negative_keywords", [])):
        if debug is not None:
            debug.update({"status": "rejected", "reason": "negative_or_commercial_filter"})
        return None

    # 2) 教程、盘点、观点、传闻等编辑型内容默认剔除
    if phrase_hits(title_lower, settings.get("editorial_phrases", [])):
        if debug is not None:
            debug.update({"status": "rejected", "reason": "editorial_or_tutorial_filter"})
        return None

    if is_commentary_only(item):
        if debug is not None:
            debug.update({"status": "rejected", "reason": "commentary_without_concrete_change"})
        return None

    if is_media_rehash(item):
        if debug is not None:
            debug.update({"status": "rejected", "reason": "media_rehash_without_new_delta"})
        return None

    change_hits = phrase_hits(text, settings.get("change_signals", []))
    require_change = bool(settings.get("require_change_signal", True))

    best: tuple[int, str, dict[str, Any]] | None = None
    saw_topic = False
    saw_identity = False
    saw_change = False
    saw_impact = False
    for key, topic in topics_cfg.get("topics", {}).items():
        keywords = [str(x).lower() for x in topic.get("keywords", [])]
        topic_hits = sum(1 for k in keywords if k and k in text)

        # Google News 的摘要可能混入站点标签，不能让摘要里的孤立品牌词决定主题身份。
        # 官方来源允许把 source 名称一起用于识别，但只有官方 Release 才能绕过变化信号门槛。
        is_official_release = item.official and "release" in item.source.lower()
        identity_text = (
            f"{item.title} {item.source}".lower()
            if item.official
            else title_lower
        )

        strong_hits = phrase_hits(identity_text, topic.get("strong_keywords", []))
        ambiguous_hits = phrase_hits(identity_text, topic.get("ambiguous_keywords", []))
        context_hits = phrase_hits(text, topic.get("context_keywords", []))
        exclude_hits = phrase_hits(text, topic.get("exclude_keywords", []))

        has_disambiguation_rules = bool(
            topic.get("strong_keywords") or topic.get("ambiguous_keywords")
        )
        if topic_hits or strong_hits or ambiguous_hits:
            saw_topic = True
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
            saw_identity = True
        elif topic_hits == 0:
            continue
        else:
            saw_identity = True

        direct_hits = strong_hits or phrase_hits(identity_text, topic.get("direct_keywords", []))
        impact_hits = phrase_hits(text, topic.get("impact_keywords", []))

        # 官方 Release 源本身就代表真实变化；聚合/媒体内容必须出现明确变化信号。
        if require_change and change_hits == 0 and not is_official_release:
            continue
        saw_change = True

        # 只相关还不够：必须能指向具体工作流影响。
        # 有消歧规则时：精确 strong anchor / 官方 Release 可直接放行；
        # 仅靠歧义词时必须命中 impact_keywords。
        # 无消歧规则的普通主题保持原有 direct_keywords 兼容逻辑。
        if has_disambiguation_rules:
            if impact_hits == 0 and strong_hits == 0 and not is_official_release:
                continue
        else:
            if impact_hits == 0 and direct_hits == 0 and not is_official_release:
                continue
        saw_impact = True

        base = int(topic.get("weight", 1))
        score = base + item.trust

        # 高可信官方/主流发布方加权。Google News 常把发布方名称放在标题尾部。
        preferred_publishers = topics_cfg.get("source_quality", {}).get("preferred_publishers", [])
        if phrase_hits(text, preferred_publishers):
            score += 2
        if item.official:
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
        if debug is not None:
            if not saw_topic:
                reason = "no_topic_match"
            elif not saw_identity:
                reason = "entity_disambiguation_failed"
            elif not saw_change:
                reason = "no_change_signal"
            elif not saw_impact:
                reason = "no_workflow_impact"
            else:
                reason = "no_eligible_topic"
            debug.update({"status": "rejected", "reason": reason})
        return None

    score, key, topic = best
    item.score = score
    item.topic_key = key
    item.topic_label = str(topic.get("label", key))
    item.impact = build_impact_reason(item, topic)
    if debug is not None:
        debug.update(
            {
                "status": "scored",
                "reason": "passed_quality_gate",
                "topic": key,
                "score": score,
                "impact": item.impact,
                "official": item.official,
                "product_key": item.product_key,
                "event_tags": list(item.event_tags),
            }
        )
    return item


def dedupe(items: list[Item]) -> list[Item]:
    result: list[Item] = []
    seen_urls: set[str] = set()
    seen_keys: list[str] = []
    for item in sorted(items, key=lambda x: (x.score, x.trust, x.published), reverse=True):
        if item.link in seen_urls:
            continue
        key = title_key(item.title)
        if not key:
            continue
        if any(key == old or SequenceMatcher(None, key, old).ratio() >= 0.84 for old in seen_keys):
            continue
        if any(same_product_event(item, old) for old in result):
            continue
        seen_urls.add(item.link)
        seen_keys.append(key)
        result.append(item)
    return result

def select_with_diagnostics(
    items: list[Item],
    topics_cfg: dict[str, Any],
    now: datetime | None = None,
    history: list[dict[str, Any]] | None = None,
) -> tuple[list[Item], list[dict[str, Any]]]:
    settings = topics_cfg.get("settings", {})
    lookback_hours = int(settings.get("lookback_hours", 30))
    min_score = int(settings.get("min_score", 13))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)
    history = history or []

    scored: list[Item] = []
    diagnostics: list[dict[str, Any]] = []
    diag_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for item in items:
        diag: dict[str, Any] = {
            "title": item.title,
            "link": item.link,
            "source": item.source,
            "published": item.published.isoformat(),
            "official": item.official,
        }
        diagnostics.append(diag)
        diag_by_key[(item.link, item.title)] = diag

        if item.published < cutoff or item.published > now + timedelta(hours=1):
            diag.update(
                {
                    "status": "rejected",
                    "reason": "outside_time_window",
                    "lookback_hours": lookback_hours,
                }
            )
            continue

        score_debug: dict[str, Any] = {}
        candidate = score_item(item, topics_cfg, debug=score_debug)
        diag.update(score_debug)
        if candidate is None:
            continue
        if candidate.score < min_score:
            diag.update(
                {
                    "status": "rejected",
                    "reason": "below_min_score",
                    "min_score": min_score,
                }
            )
            continue

        is_old, old = history_duplicate(candidate, history, settings)
        if is_old:
            diag.update(
                {
                    "status": "rejected",
                    "reason": "cross_day_duplicate",
                    "previous_title": old.get("title") if old else None,
                    "previous_pushed_at": old.get("pushed_at") if old else None,
                }
            )
            continue

        diag.update({"status": "candidate", "reason": "passed_quality_gate"})
        scored.append(candidate)

    deduped = dedupe(scored)
    deduped_keys = {(x.link, x.title) for x in deduped}
    for item in scored:
        key = (item.link, item.title)
        if key not in deduped_keys:
            diag_by_key[key].update(
                {"status": "rejected", "reason": "same_run_duplicate"}
            )

    selected: list[Item] = []
    selected_keys: set[tuple[str, str]] = set()
    for key, topic in topics_cfg.get("topics", {}).items():
        quota = int(topic.get("max_items", 3))
        group = [item for item in deduped if item.topic_key == key]
        for item in group[:quota]:
            selected.append(item)
            selected_keys.add((item.link, item.title))
        for item in group[quota:]:
            diag_by_key[(item.link, item.title)].update(
                {"status": "rejected", "reason": "category_quota_exceeded", "quota": quota}
            )

    # 同一具体产品默认每天只保留 1 条，避免一个模型/版本占满整个分类。
    product_seen: set[str] = set()
    product_limited: list[Item] = []
    for item in selected:
        if item.product_key and item.product_key in product_seen:
            diag_by_key[(item.link, item.title)].update(
                {"status": "rejected", "reason": "same_product_daily_limit"}
            )
            continue
        if item.product_key:
            product_seen.add(item.product_key)
        product_limited.append(item)
    selected = product_limited

    for item in selected:
        diag_by_key[(item.link, item.title)].update(
            {
                "status": "selected",
                "reason": "selected_for_delivery",
                "topic": item.topic_key,
                "score": item.score,
                "impact": item.impact,
            }
        )

    return selected, diagnostics


def select(items: list[Item], topics_cfg: dict[str, Any], now: datetime | None = None) -> list[Item]:
    selected, _ = select_with_diagnostics(items, topics_cfg, now=now, history=[])
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
            "translation_localization": "🌐",
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
                stars = importance_stars(item.score)
                summary = short_summary(item.summary)
                body = (
                    f"**{idx}. [{item.title}]({item.link})**\n"
                    f"重要度：{stars}（{item.score}分）｜来源：{item.source}\n"
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


def save_debug(
    items: list[Item],
    errors: list[str],
    diagnostics: list[dict[str, Any]] | None = None,
    history_count: int = 0,
) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
        "history_count": history_count,
        "selected_count": len(items),
        "items": [
            {
                "title": x.title,
                "link": x.link,
                "source": x.source,
                "published": x.published.isoformat(),
                "topic": x.topic_label,
                "score": x.score,
                "impact": x.impact,
                "official": x.official,
                "product_key": x.product_key,
                "event_tags": list(x.event_tags),
            }
            for x in items
        ],
        "diagnostics": diagnostics or [],
    }
    DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不发送飞书")
    parser.add_argument(
        "--skip-if-sent-today",
        action="store_true",
        help="若北京时间当天已成功发送，则直接退出；仅供定时重试使用",
    )
    args = parser.parse_args()
    topics_cfg = load_toml(ROOT / "config" / "topics.toml")
    if args.skip_if_sent_today and already_delivered_today(topics_cfg):
        print(
            f"already delivered on {delivery_local_date(topics_cfg)}; "
            "scheduled retry skipped"
        )
        return 0

    sources_cfg = load_toml(ROOT / "config" / "sources.toml")
    raw, errors = collect(sources_cfg)
    history = load_history()
    selected, diagnostics = select_with_diagnostics(
        raw,
        topics_cfg,
        history=history,
    )
    save_debug(selected, errors, diagnostics, history_count=len(history))
    payload = report_payload(selected, errors, topics_cfg)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        print("ERROR: FEISHU_WEBHOOK is not configured", file=sys.stderr)
        return 2
    send_feishu(webhook, payload)
    save_history(history, selected, topics_cfg)
    save_last_delivery(selected, errors, topics_cfg)
    print(
        f"sent {len(selected)} items; source_errors={len(errors)}; "
        f"diagnostics={len(diagnostics)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
