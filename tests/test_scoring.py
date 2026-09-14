"""Unit tests for scoring."""

import unittest
from core.models import NewsItem
from core.scoring import compute_importance, compute_source_density


class TestComputeImportance(unittest.TestCase):
    def test_default_score(self):
        item = NewsItem(title="A", url="U", source="unique_source")
        items = [item]
        result = compute_importance(item, items)
        self.assertGreater(result, 1.0)

    def test_source_diversity_bonus(self):
        item = NewsItem(title="A", url="U", source="unique")
        others = [
            NewsItem(title="B", url="U2", source="other1"),
            NewsItem(title="C", url="U3", source="other2"),
        ]
        all_items = [item] + others
        result = compute_importance(item, all_items)
        self.assertGreater(result, 1.0)

    def test_no_diversity_bonus_for_duplicate_source(self):
        item = NewsItem(title="A", url="U", source="same")
        other = NewsItem(title="B", url="U2", source="same")
        all_items = [item, other]
        result = compute_importance(item, all_items)
        self.assertEqual(result, 1.0)


class TestComputeSourceDensity(unittest.TestCase):
    def test_single_source(self):
        items = [
            NewsItem(title="A", url="U", source="s1"),
            NewsItem(title="B", url="U2", source="s1"),
        ]
        result = compute_source_density(items)
        self.assertEqual(result, {"s1": 2})

    def test_multiple_sources(self):
        items = [
            NewsItem(title="A", url="U", source="s1"),
            NewsItem(title="B", url="U2", source="s2"),
            NewsItem(title="C", url="U3", source="s1"),
        ]
        result = compute_source_density(items)
        self.assertEqual(result, {"s1": 2, "s2": 1})

    def test_empty_list(self):
        result = compute_source_density([])
        self.assertEqual(result, {})
