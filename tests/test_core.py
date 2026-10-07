import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import Item, canonical_url, dedupe, parse_feed_bytes, score_item

TOPICS = {
    "settings": {"negative_keywords": ["sponsored"]},
    "topics": {
        "subtitle": {
            "label": "字幕",
            "weight": 5,
            "keywords": ["faster-whisper", "whisper"],
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
        item = Item("faster-whisper release", "https://example.com/a", "Whisper update", datetime.now(timezone.utc), "test", 5)
        result = score_item(item, TOPICS)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result.score, 8)
        self.assertEqual(result.topic_label, "字幕")

    def test_negative_filter(self):
        item = Item("sponsored Whisper article", "https://example.com/a", "", datetime.now(timezone.utc), "test", 5)
        self.assertIsNone(score_item(item, TOPICS))

    def test_dedupe_similar_titles(self):
        now = datetime.now(timezone.utc)
        a = Item("Whisper v2 release", "https://a", "", now, "x", 5, score=10)
        b = Item("Whisper v2 release!", "https://b", "", now, "y", 4, score=9)
        self.assertEqual(len(dedupe([a, b])), 1)

    def test_parse_rss_and_atom(self):
        rss = b'''<?xml version="1.0"?><rss><channel><item><title>Whisper update</title><link>https://example.com/a</link><description>News</description><pubDate>Wed, 07 Oct 2026 01:00:00 GMT</pubDate></item></channel></rss>'''
        atom = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Release v1</title><link href="https://example.com/b"/><summary>Notes</summary><updated>2026-10-07T01:00:00Z</updated></entry></feed>'''
        self.assertEqual(len(parse_feed_bytes(rss, "rss", 3)), 1)
        self.assertEqual(len(parse_feed_bytes(atom, "atom", 5)), 1)


if __name__ == "__main__":
    unittest.main()
