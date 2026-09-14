"""Tests for source normalization."""
import unittest
from core.evidence import Evidence
from core.normalization import normalize_url, normalize_sources, deduplicate_sources


class TestNormalizeUrl(unittest.TestCase):
    def test_basic_url(self):
        self.assertEqual(normalize_url("https://example.com"), "https://example.com")

    def test_trailing_slash(self):
        self.assertEqual(normalize_url("https://example.com/"), "https://example.com")

    def test_uppercase_domain(self):
        self.assertEqual(normalize_url("https://EXAMPLE.COM/article"), "https://example.com/article")

    def test_missing_scheme(self):
        self.assertEqual(normalize_url("example.com"), "https://example.com")


class TestNormalizeSources(unittest.TestCase):
    def test_normalizes_urls(self):
        ev = Evidence(source_url="https://Example.COM/", source_title="Title", publisher="Pub")
        result = normalize_sources([ev])
        self.assertEqual(result[0].source_url, "https://example.com")


class TestDeduplicateSources(unittest.TestCase):
    def test_empty_list(self):
        result = deduplicate_sources([])
        self.assertEqual(result, [])

    def test_no_duplicates(self):
        ev1 = Evidence(source_url="https://a.com", source_title="A", publisher="P")
        ev2 = Evidence(source_url="https://b.com", source_title="B", publisher="P")
        result = deduplicate_sources([ev1, ev2])
        self.assertEqual(len(result), 2)

    def test_url_duplicates(self):
        ev1 = Evidence(source_url="https://a.com", source_title="A", publisher="P")
        ev2 = Evidence(source_url="https://a.com", source_title="A2", publisher="P2")
        result = deduplicate_sources([ev1, ev2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source_title, "A")

    def test_title_duplicates(self):
        ev1 = Evidence(source_url="https://a.com", source_title="Breaking News", publisher="P")
        ev2 = Evidence(source_url="https://b.com", source_title="Breaking News", publisher="P2")
        result = deduplicate_sources([ev1, ev2])
        self.assertEqual(len(result), 1)

    def test_preserves_order(self):
        ev1 = Evidence(source_url="https://a.com", source_title="A", publisher="P")
        ev2 = Evidence(source_url="https://b.com", source_title="B", publisher="P")
        ev3 = Evidence(source_url="https://a.com", source_title="A", publisher="P3")
        result = deduplicate_sources([ev1, ev2, ev3])
        self.assertEqual(result[0].publisher, "P")
        self.assertEqual(result[1].publisher, "P")
        self.assertEqual(len(result), 2)

    def test_empty_title_not_deduped_by_title(self):
        ev1 = Evidence(source_url="https://a.com", source_title="", publisher="P")
        ev2 = Evidence(source_url="https://b.com", source_title="", publisher="P2")
        result = deduplicate_sources([ev1, ev2])
        self.assertEqual(len(result), 2)
