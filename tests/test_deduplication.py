"""Unit tests for deduplication."""

import unittest
from core.models import NewsItem
from core.deduplication import deduplicate


class TestDeduplicate(unittest.TestCase):
    def test_empty_list(self):
        result = deduplicate([])
        self.assertEqual(result, [])

    def test_no_duplicates(self):
        items = [
            NewsItem(title="A", url="https://a.com", source="s1"),
            NewsItem(title="B", url="https://b.com", source="s2"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 2)

    def test_exact_url_duplicates(self):
        items = [
            NewsItem(title="A", url="https://example.com", source="s1"),
            NewsItem(title="A2", url="https://example.com", source="s2"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "s1")

    def test_url_with_trailing_slash(self):
        items = [
            NewsItem(title="A", url="https://example.com/", source="s1"),
            NewsItem(title="A2", url="https://example.com", source="s2"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 1)

    def test_title_only_duplicates(self):
        items = [
            NewsItem(title="Breaking News", url="https://a.com", source="s1"),
            NewsItem(title="Breaking News", url="https://b.com", source="s2"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "s1")

    def test_mixed_no_duplicates(self):
        items = [
            NewsItem(title="A", url="https://a.com", source="s1"),
            NewsItem(title="B", url="https://b.com", source="s2"),
            NewsItem(title="C", url="https://c.com", source="s3"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 3)

    def test_preserves_order(self):
        items = [
            NewsItem(title="A", url="https://a.com", source="s1"),
            NewsItem(title="B", url="https://b.com", source="s2"),
            NewsItem(title="A", url="https://a.com", source="s3"),
        ]
        result = deduplicate(items)
        self.assertEqual(result[0].source, "s1")
        self.assertEqual(result[1].source, "s2")

    def test_empty_title_not_deduped_by_title(self):
        items = [
            NewsItem(title="", url="https://a.com", source="s1"),
            NewsItem(title="", url="https://b.com", source="s2"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 2)

    def test_case_insensitive_url(self):
        items = [
            NewsItem(title="A", url="https://Example.COM", source="s1"),
            NewsItem(title="A", url="https://example.com", source="s2"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 1)
