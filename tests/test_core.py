import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import Item, canonical_url, dedupe, parse_feed_bytes, score_item, select

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
            Item(f"alpha update news {i}", f"https://a/{i}", "", now, "x", 5) for i in range(4)
        ] + [
            Item(f"beta update news {i}", f"https://b/{i}", "", now, "x", 5) for i in range(3)
        ]
        chosen = select(items, cfg, now=now)
        self.assertEqual(sum(1 for x in chosen if x.topic_key == "a"), 2)
        self.assertEqual(sum(1 for x in chosen if x.topic_key == "b"), 1)

    def test_parse_rss_and_atom(self):
        rss = b'''<?xml version="1.0"?><rss><channel><item><title>Whisper update</title><link>https://example.com/a</link><description>News</description><pubDate>Wed, 07 Oct 2026 01:00:00 GMT</pubDate></item></channel></rss>'''
        atom = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Release v1</title><link href="https://example.com/b"/><summary>Notes</summary><updated>2026-10-07T01:00:00Z</updated></entry></feed>'''
        self.assertEqual(len(parse_feed_bytes(rss, "rss", 3)), 1)
        self.assertEqual(len(parse_feed_bytes(atom, "atom", 5)), 1)


if __name__ == "__main__":
    unittest.main()
