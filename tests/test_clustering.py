"""Unit tests for clustering using Jaccard similarity."""

import unittest
from core.models import NewsItem
from core.clustering import cluster, _jaccard, _tokenize


class TestTokenize(unittest.TestCase):
    def test_basic_tokenization(self):
        result = _tokenize("Hello World")
        self.assertEqual(result, {"hello", "world"})

    def test_case_insensitive(self):
        result = _tokenize("HELLO world")
        self.assertEqual(result, {"hello", "world"})

    def test_strips_punctuation(self):
        result = _tokenize("Hello, World!")
        self.assertEqual(result, {"hello", "world"})

    def test_empty_string(self):
        result = _tokenize("")
        self.assertEqual(result, set())

    def test_numbers_and_special_chars(self):
        result = _tokenize("Test123 !@#")
        self.assertEqual(result, {"test"})


class TestJaccard(unittest.TestCase):
    def test_identical_sets(self):
        self.assertEqual(_jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_no_overlap(self):
        self.assertEqual(_jaccard({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial_overlap(self):
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"b", "c"}), 1/3)

    def test_empty_set(self):
        self.assertEqual(_jaccard({"a"}, set()), 0.0)
        self.assertEqual(_jaccard(set(), set()), 0.0)


class TestCluster(unittest.TestCase):
    def test_empty_input(self):
        result = cluster([])
        self.assertEqual(result, [])

    def test_single_item(self):
        items = [NewsItem(title="Breaking news", url="u1", source="s1")]
        result = cluster(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].story_id, "cluster-0")
        self.assertEqual(len(result[0].items), 1)

    def test_items_with_high_overlap(self):
        items = [
            NewsItem(title="AI machine learning", url="u1", source="s1"),
            NewsItem(title="AI deep learning", url="u2", source="s2"),
        ]
        result = cluster(items, similarity_threshold=0.3)
        self.assertEqual(len(result), 1)

    def test_items_with_no_overlap(self):
        items = [
            NewsItem(title="cat dog", url="u1", source="s1"),
            NewsItem(title="xyz abc", url="u2", source="s2"),
        ]
        result = cluster(items, similarity_threshold=0.3)
        self.assertEqual(len(result), 2)

    def test_similarity_threshold_parameter(self):
        items = [
            NewsItem(title="AI technology", url="u1", source="s1"),
            NewsItem(title="AI innovation", url="u2", source="s2"),
        ]
        result_low = cluster(items, similarity_threshold=0.1)
        result_high = cluster(items, similarity_threshold=0.9)
        self.assertEqual(len(result_low), 1)
        self.assertGreaterEqual(len(result_high), 1)

    def test_jaccard_correctness(self):
        sim = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        self.assertAlmostEqual(sim, 2/4)

    def test_common_words_not_merged_at_high_threshold(self):
        items = [
            NewsItem(title="the and of in", url="u1", source="s1"),
            NewsItem(title="the or for to", url="u2", source="s2"),
        ]
        result = cluster(items, similarity_threshold=0.5)
        self.assertEqual(len(result), 2)
