import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import Item, canonical_url, dedupe, parse_feed_bytes, score_item, select, load_toml, normalize_product_key, event_tags_for_text, history_duplicate


def load_test_config():
    return load_toml(ROOT / "config" / "topics.toml")

TOPICS = {
    "settings": {
        "negative_keywords": ["sponsored"],
        "editorial_phrases": ["tutorial", "best ai tools"],
        "low_value_phrases": ["review"],
        "change_signals": ["release", "update", "released", "updated"],
        "require_change_signal": True,
    },
    "topics": {
        "subtitle": {
            "label": "字幕",
            "weight": 5,
            "keywords": ["faster-whisper", "whisper"],
            "direct_keywords": ["faster-whisper"],
            "impact_keywords": ["timestamp", "accuracy"],
            "impact": "impact",
        }
    },
}


class CoreTests(unittest.TestCase):
    def test_canonical_url_removes_tracking(self):
        self.assertEqual(
            canonical_url("https://example.com/a/?utm_source=x&id=3#top"),
            "https://example.com/a?id=3",
        )

    def test_score_topic(self):
        item = Item("faster-whisper release", "https://example.com/a", "Whisper timestamp accuracy update", datetime.now(timezone.utc), "test", 5)
        result = score_item(item, TOPICS)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.score, 8)
        self.assertEqual(result.topic_label, "字幕")

    def test_generic_keyword_without_change_is_rejected(self):
        item = Item("Whisper is changing the AI world", "https://example.com/x", "A broad opinion about Whisper.", datetime.now(timezone.utc), "news", 3)
        self.assertIsNone(score_item(item, TOPICS))

    def test_tutorial_is_rejected(self):
        item = Item("Whisper tutorial for beginners", "https://example.com/t", "Whisper update guide", datetime.now(timezone.utc), "news", 3)
        self.assertIsNone(score_item(item, TOPICS))

    def test_real_workflow_change_is_kept(self):
        item = Item("faster-whisper released update", "https://example.com/r", "Improved timestamp accuracy", datetime.now(timezone.utc), "faster-whisper Releases", 5)
        result = score_item(item, TOPICS)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.score, 13)

    def test_negative_filter(self):
        item = Item("sponsored Whisper article", "https://example.com/a", "", datetime.now(timezone.utc), "test", 5)
        self.assertIsNone(score_item(item, TOPICS))

    def test_dedupe_similar_titles(self):
        now = datetime.now(timezone.utc)
        a = Item("Whisper v2 release", "https://a", "", now, "x", 5, score=10)
        b = Item("Whisper v2 release!", "https://b", "", now, "y", 4, score=9)
        self.assertEqual(len(dedupe([a, b])), 1)

    def test_dedupe_google_news_publisher_suffix(self):
        now = datetime.now(timezone.utc)
        a = Item("Seedance 2.0 released with new API - Reuters", "https://a", "", now, "GoogleNews", 3, score=18)
        b = Item("Seedance 2.0 released with new API - The Verge", "https://b", "", now, "GoogleNews", 3, score=17)
        self.assertEqual(len(dedupe([a, b])), 1)

    def test_category_quotas(self):
        now = datetime.now(timezone.utc)
        cfg = {
            "settings": {
                "negative_keywords": [], "editorial_phrases": [], "low_value_phrases": [],
                "change_signals": ["update"], "require_change_signal": True,
                "lookback_hours": 30, "min_score": 1
            },
            "topics": {
                "a": {"label": "A", "weight": 5, "max_items": 2, "keywords": ["alpha"], "direct_keywords": ["alpha"], "impact_keywords": [], "impact": "a"},
                "b": {"label": "B", "weight": 5, "max_items": 1, "keywords": ["beta"], "direct_keywords": ["beta"], "impact_keywords": [], "impact": "b"},
            },
        }
        items = [
            Item("alpha update adds timestamp alignment", "https://a/1", "", now, "x", 5),
            Item("alpha update improves speaker diarization", "https://a/2", "", now, "x", 5),
            Item("alpha update reduces CUDA memory use", "https://a/3", "", now, "x", 5),
            Item("alpha update adds batch processing", "https://a/4", "", now, "x", 5),
            Item("beta update adds timeline export", "https://b/1", "", now, "x", 5),
            Item("beta update changes API pricing", "https://b/2", "", now, "x", 5),
            Item("beta update adds workflow automation", "https://b/3", "", now, "x", 5),
        ]
        chosen = select(items, cfg, now=now)
        self.assertEqual(sum(1 for x in chosen if x.topic_key == "a"), 2)
        self.assertEqual(sum(1 for x in chosen if x.topic_key == "b"), 1)


    def test_sora_bus_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "Toyota and Isuzu launch new SORA hydrogen fuel cell bus",
            "https://example.com/sora-bus",
            "The vehicle has 300 km range and new commercial vehicle features.",
            datetime.now(timezone.utc),
            "GoogleNews-Seedance-AIVideo",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_runway_airport_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "Airport runway upgrade launched with new lighting system",
            "https://example.com/runway",
            "Airport runway construction and aviation update.",
            datetime.now(timezone.utc),
            "GoogleNews-Seedance-AIVideo",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_gemini_zodiac_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "Gemini horoscope update for October",
            "https://example.com/gemini-zodiac",
            "Zodiac and constellation forecast.",
            datetime.now(timezone.utc),
            "GoogleNews-Models",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_claude_person_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "Claude Monet exhibition opens with updated collection",
            "https://example.com/claude-monet",
            "Museum exhibition about Claude Monet paintings.",
            datetime.now(timezone.utc),
            "GoogleNews-Models",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_flux_physics_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "Magnetic flux model updated for solar research",
            "https://example.com/flux-physics",
            "Physics paper on magnetic flux and solar flux.",
            datetime.now(timezone.utc),
            "GoogleNews-Image",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_index_translate_is_kept(self):
        cfg = load_test_config()
        item = Item(
            "Bilibili releases Index-Translate and Index-Echo speech translation models",
            "https://example.com/index-translate",
            "Open source subtitle translation model supports S2TT, Spanish, terminology consistency, GGUF and local deployment.",
            datetime.now(timezone.utc),
            "GoogleNews-Translation-Localization",
            3,
        )
        result = score_item(item, cfg)
        self.assertIsNotNone(result)
        self.assertEqual(result.topic_key, "translation_localization")

    def test_parse_rss_and_atom(self):
        rss = b'''<?xml version="1.0"?><rss><channel><item><title>Whisper update</title><link>https://example.com/a</link><description>News</description><pubDate>Wed, 07 Oct 2026 01:00:00 GMT</pubDate></item></channel></rss>'''
        atom = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Release v1</title><link href="https://example.com/b"/><summary>Notes</summary><updated>2026-10-07T01:00:00Z</updated></entry></feed>'''
        self.assertEqual(len(parse_feed_bytes(rss, "rss", 3)), 1)
        self.assertEqual(len(parse_feed_bytes(atom, "atom", 5)), 1)


    def test_product_key_for_gpt_sol_variants(self):
        self.assertEqual(
            normalize_product_key("OpenAI推出GPT-6.1 Sol Ultrafast API"),
            "gpt-6.1-sol-ultrafast",
        )

    def test_event_dedupe_same_product_same_event(self):
        now = datetime.now(timezone.utc)
        a = Item(
            "OpenAI推出GPT-6.1 Sol Ultrafast API定价达标准版6倍",
            "https://a",
            "API pricing update",
            now,
            "GoogleNews-Models",
            3,
            score=29,
        )
        b = Item(
            "OpenAI推出GPT-6.1 Sol Ultrafast版：6倍价格、最高8倍速度",
            "https://b",
            "pricing and speed update",
            now,
            "GoogleNews-Models",
            3,
            score=27,
        )
        for item in (a, b):
            item.product_key = normalize_product_key(f"{item.title} {item.summary}")
            item.event_tags = event_tags_for_text(f"{item.title} {item.summary}")
        self.assertEqual(len(dedupe([a, b])), 1)

    def test_media_rehash_release_without_new_delta_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "OpenAI推出GPT-6.1 Sol",
            "https://example.com/rehash",
            "OpenAI发布GPT-6.1 Sol。",
            datetime.now(timezone.utc),
            "GoogleNews-Models",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_commentary_short_drama_without_concrete_change_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "约九成公司亏损？媒体：别被AI短剧的数字繁荣骗了",
            "https://example.com/commentary",
            "行业观察文章讨论短剧成本与播放量。",
            datetime.now(timezone.utc),
            "GoogleNews-ShortDrama",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_same_product_daily_limit(self):
        now = datetime.now(timezone.utc)
        cfg = load_test_config()
        items = [
            Item(
                "OpenAI推出GPT-6.1 Sol API pricing update",
                "https://example.com/a",
                "API pricing price update",
                now,
                "GoogleNews-Models",
                3,
            ),
            Item(
                "GPT-6.1 Sol adds new tool use capability",
                "https://example.com/b",
                "OpenAI update adds support for tool use API",
                now,
                "GoogleNews-Models",
                3,
            ),
        ]
        chosen = select(items, cfg, now=now)
        self.assertLessEqual(
            sum(1 for x in chosen if x.product_key == "gpt-6.1-sol"),
            1,
        )


    def test_base_sol_and_ultrafast_are_distinct_products(self):
        self.assertEqual(
            normalize_product_key("OpenAI GPT-6.1 Sol"),
            "gpt-6.1-sol",
        )
        self.assertEqual(
            normalize_product_key("OpenAI GPT-6.1 Sol Ultrafast"),
            "gpt-6.1-sol-ultrafast",
        )


    def test_soft_quota_allows_high_score_overflow_to_hard_cap(self):
        now = datetime.now(timezone.utc)
        cfg = {
            "settings": {
                "negative_keywords": [],
                "editorial_phrases": [],
                "low_value_phrases": [],
                "change_signals": ["update"],
                "require_change_signal": True,
                "lookback_hours": 30,
                "min_score": 1,
                "overflow_min_score": 18,
                "total_max_items": 15,
            },
            "topics": {
                "a": {
                    "label": "A",
                    "weight": 20,
                    "max_items": 8,
                    "soft_max_items": 5,
                    "hard_max_items": 8,
                    "overflow_min_score": 18,
                    "keywords": ["alpha"],
                    "direct_keywords": ["alpha"],
                    "impact_keywords": [],
                    "impact": "a",
                }
            },
        }
        items = [
            Item("alpha update adds timestamp alignment", "https://a/1", "", now, "x", 5),
            Item("alpha update improves speaker diarization", "https://a/2", "", now, "x", 5),
            Item("alpha update reduces CUDA memory use", "https://a/3", "", now, "x", 5),
            Item("alpha update adds batch workflow export", "https://a/4", "", now, "x", 5),
            Item("alpha update changes API pricing", "https://a/5", "", now, "x", 5),
            Item("alpha update expands context window", "https://a/6", "", now, "x", 5),
            Item("alpha update improves tool use reasoning", "https://a/7", "", now, "x", 5),
        ]
        chosen = select(items, cfg, now=now)
        self.assertEqual(len(chosen), 7)

    def test_soft_quota_blocks_low_score_overflow(self):
        now = datetime.now(timezone.utc)
        cfg = {
            "settings": {
                "negative_keywords": [],
                "editorial_phrases": [],
                "low_value_phrases": [],
                "change_signals": ["update"],
                "require_change_signal": True,
                "lookback_hours": 30,
                "min_score": 1,
                "overflow_min_score": 18,
                "total_max_items": 15,
            },
            "topics": {
                "a": {
                    "label": "A",
                    "weight": 1,
                    "max_items": 8,
                    "soft_max_items": 5,
                    "hard_max_items": 8,
                    "overflow_min_score": 18,
                    "keywords": ["alpha"],
                    "direct_keywords": ["alpha"],
                    "impact_keywords": [],
                    "impact": "a",
                }
            },
        }
        items = [
            Item("alpha update adds timestamp alignment", "https://a/1", "", now, "x", 1),
            Item("alpha update improves speaker diarization", "https://a/2", "", now, "x", 1),
            Item("alpha update reduces CUDA memory use", "https://a/3", "", now, "x", 1),
            Item("alpha update adds batch workflow export", "https://a/4", "", now, "x", 1),
            Item("alpha update changes API pricing", "https://a/5", "", now, "x", 1),
            Item("alpha update expands context window", "https://a/6", "", now, "x", 1),
            Item("alpha update improves tool use reasoning", "https://a/7", "", now, "x", 1),
        ]
        chosen = select(items, cfg, now=now)
        self.assertEqual(len(chosen), 5)

    def test_non_workflow_boycott_opinion_is_rejected(self):
        cfg = load_test_config()
        item = Item(
            "陶哲轩公开声援抵制OpenAI，数学界与AI巨头矛盾升级",
            "https://example.com/opinion",
            "A public controversy and boycott statement.",
            datetime.now(timezone.utc),
            "GoogleNews-Models",
            3,
        )
        self.assertIsNone(score_item(item, cfg))

    def test_daily_total_hard_cap(self):
        now = datetime.now(timezone.utc)
        cfg = {
            "settings": {
                "negative_keywords": [],
                "editorial_phrases": [],
                "low_value_phrases": [],
                "change_signals": ["update"],
                "require_change_signal": True,
                "lookback_hours": 30,
                "min_score": 1,
                "total_max_items": 3,
            },
            "topics": {
                "a": {
                    "label": "A",
                    "weight": 20,
                    "max_items": 5,
                    "keywords": ["alpha"],
                    "direct_keywords": ["alpha"],
                    "impact_keywords": [],
                    "impact": "a",
                },
                "b": {
                    "label": "B",
                    "weight": 19,
                    "max_items": 5,
                    "keywords": ["beta"],
                    "direct_keywords": ["beta"],
                    "impact_keywords": [],
                    "impact": "b",
                },
            },
        }
        items = [
            Item("alpha update adds timestamp alignment", "https://a/1", "", now, "x", 5),
            Item("alpha update changes API pricing", "https://a/2", "", now, "x", 5),
            Item("beta update adds timeline export", "https://b/1", "", now, "x", 5),
            Item("beta update improves local batch automation", "https://b/2", "", now, "x", 5),
        ]
        chosen = select(items, cfg, now=now)
        self.assertEqual(len(chosen), 3)


    def test_same_day_history_does_not_block_manual_rerun(self):
        cfg = load_test_config()
        settings = cfg["settings"]
        now = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)  # 北京时间 11:00
        item = Item(
            "OpenAI GPT-6.1 Sol Ultrafast API pricing update",
            "https://example.com/news",
            "API pricing update",
            now,
            "GoogleNews-Models",
            3,
        )
        scored = score_item(item, cfg)
        self.assertIsNotNone(scored)
        history = [{
            "title": item.title,
            "title_key": "same",
            "link": item.link,
            "product_key": scored.product_key,
            "event_tags": list(scored.event_tags),
            "pushed_at": "2026-10-09T01:00:00+00:00",
        }]
        duplicate, _ = history_duplicate(scored, history, settings, now=now)
        self.assertFalse(duplicate)

    def test_previous_day_history_still_blocks_duplicate(self):
        cfg = load_test_config()
        settings = cfg["settings"]
        now = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)
        item = Item(
            "OpenAI GPT-6.1 Sol Ultrafast API pricing update",
            "https://example.com/news",
            "API pricing update",
            now,
            "GoogleNews-Models",
            3,
        )
        scored = score_item(item, cfg)
        self.assertIsNotNone(scored)
        history = [{
            "title": item.title,
            "title_key": "same",
            "link": item.link,
            "product_key": scored.product_key,
            "event_tags": list(scored.event_tags),
            "pushed_at": "2026-10-08T01:00:00+00:00",
        }]
        duplicate, _ = history_duplicate(scored, history, settings, now=now)
        self.assertTrue(duplicate)


if __name__ == "__main__":
    unittest.main()
