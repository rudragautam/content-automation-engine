"""Tests for Evidence model."""
import unittest
from core.evidence import Evidence


class TestEvidence(unittest.TestCase):
    def test_create_evidence(self):
        ev = Evidence(
            source_url="https://example.com",
            source_title="Test Article",
            publisher="Test Publisher",
            published_at="2026-01-01",
            extracted_text="Some text",
            retrieved_at="2026-09-14",
        )
        self.assertEqual(ev.source_url, "https://example.com")
        self.assertEqual(ev.source_title, "Test Article")
        self.assertEqual(ev.publisher, "Test Publisher")
        self.assertEqual(ev.published_at, "2026-01-01")
        self.assertEqual(ev.extracted_text, "Some text")
        self.assertEqual(ev.retrieved_at, "2026-09-14")

    def test_evidence_immutable(self):
        ev = Evidence(source_url="U", source_title="T", publisher="P")
        with self.assertRaises(AttributeError):
            ev.source_url = "modified"

    def test_evidence_minimal(self):
        ev = Evidence(source_url="https://example.com", source_title="Title", publisher="Pub")
        self.assertEqual(ev.published_at, None)
        self.assertEqual(ev.extracted_text, "")
        self.assertEqual(ev.retrieved_at, "")
