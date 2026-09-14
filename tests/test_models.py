"""Unit tests for domain models."""

import unittest
from core.models import NewsItem, TrendItem, StoryCluster


class TestNewsItem(unittest.TestCase):
    def test_create_news_item(self):
        item = NewsItem(
            title="Test Title",
            url="https://example.com",
            source="test-source",
        )
        self.assertEqual(item.title, "Test Title")
        self.assertEqual(item.url, "https://example.com")
        self.assertEqual(item.source, "test-source")

    def test_news_item_with_all_fields(self):
        item = NewsItem(
            title="Title",
            url="https://example.com",
            source="src",
            published_at="2026-01-01T00:00:00Z",
            content="body",
            category="tech",
            raw={"key": "val"},
        )
        self.assertEqual(item.published_at, "2026-01-01T00:00:00Z")
        self.assertEqual(item.content, "body")
        self.assertEqual(item.category, "tech")
        self.assertEqual(item.raw, {"key": "val"})

    def test_news_item_immutable(self):
        item = NewsItem(title="T", url="U", source="S")
        with self.assertRaises(AttributeError):
            item.title = "modified"


class TestTrendItem(unittest.TestCase):
    def test_create_trend_item(self):
        item = TrendItem(
            keyword="AI",
            score=95.5,
            trend_direction="up",
            region="US",
        )
        self.assertEqual(item.keyword, "AI")
        self.assertEqual(item.score, 95.5)
        self.assertEqual(item.trend_direction, "up")
        self.assertEqual(item.region, "US")

    def test_trend_item_immutable(self):
        item = TrendItem(keyword="AI", score=95.5, trend_direction="up", region="US")
        with self.assertRaises(AttributeError):
            item.keyword = "modified"


class TestStoryCluster(unittest.TestCase):
    def test_create_story_cluster(self):
        items = (
            NewsItem(title="T1", url="U1", source="S1"),
            NewsItem(title="T2", url="U2", source="S1"),
        )
        cluster = StoryCluster(
            story_id="c1",
            items=items,
            keywords=("ai", "machine"),
            importance_score=1.5,
            source_density={"S1": 2},
        )
        self.assertEqual(cluster.story_id, "c1")
        self.assertEqual(len(cluster.items), 2)
        self.assertEqual(cluster.keywords, ("ai", "machine"))
        self.assertEqual(cluster.importance_score, 1.5)
        self.assertEqual(cluster.source_density, {"S1": 2})

    def test_story_cluster_immutable(self):
        items = (NewsItem(title="T", url="U", source="S"),)
        cluster = StoryCluster(
            story_id="c1",
            items=items,
            keywords=("k1",),
            importance_score=1.0,
            source_density={"S": 1},
        )
        with self.assertRaises(AttributeError):
            cluster.story_id = "modified"
