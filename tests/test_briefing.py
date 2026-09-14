"""Tests for content briefing."""
import unittest
from core.briefing import ContentBrief, ContentItem, generate_brief
from core.claims import Claim
from core.evidence import Evidence


class TestContentBrief(unittest.TestCase):
    def test_create_brief(self):
        brief = ContentBrief(
            topic="Test Topic",
            audience="general",
            platform="youtube_long",
            format="video",
            angle="informative",
            key_points=("point1", "point2"),
            tone="neutral",
            language="en",
        )
        self.assertEqual(brief.topic, "Test Topic")
        self.assertEqual(brief.platform, "youtube_long")
        self.assertEqual(brief.key_points, ("point1", "point2"))

    def test_brief_immutable(self):
        brief = ContentBrief(topic="T", audience="A", platform="P", format="F", angle="A")
        with self.assertRaises(AttributeError):
            brief.topic = "modified"

    def test_brief_defaults(self):
        brief = ContentBrief(topic="T", audience="A", platform="P", format="F", angle="A")
        self.assertEqual(brief.key_points, ())
        self.assertEqual(brief.tone, "neutral")
        self.assertEqual(brief.language, "en")
        self.assertIsNone(brief.cta)


class TestContentItem(unittest.TestCase):
    def test_create_item(self):
        item = ContentItem(
            title="Test", body="Body", platform="youtube_short", format="short_video",
            claims=(1, 2), evidence_urls=("url1",), brief_id="abc123",
        )
        self.assertEqual(item.title, "Test")
        self.assertEqual(item.brief_id, "abc123")

    def test_content_item_defaults(self):
        item = ContentItem(title="T", body="B")
        self.assertEqual(item.claims, ())
        self.assertEqual(item.evidence_urls, ())
        self.assertEqual(item.platform, "")


class TestGenerateBrief(unittest.TestCase):
    def test_generates_brief(self):
        claims = [Claim(claim_id="c1", text="Test claim", topic="test", is_factual=True)]
        evidence = [Evidence(source_url="https://a.com", source_title="A", publisher="P",
                             extracted_text="Test evidence")]
        brief = generate_brief(topic="My Topic", checked_claims=claims, evidence=evidence)
        self.assertEqual(brief.topic, "My Topic")
        self.assertEqual(brief.factual_claims, tuple(claims))
        self.assertEqual(brief.supporting_evidence, tuple(evidence))
        self.assertTrue(len(brief.key_points) > 0)

    def test_brief_preserves_claims(self):
        claims = [
            Claim(claim_id="c1", text="Claim 1", topic="t", is_factual=True),
            Claim(claim_id="c2", text="Claim 2", topic="t", is_factual=False),
        ]
        evidence = []
        brief = generate_brief(topic="T", checked_claims=claims, evidence=evidence)
        self.assertEqual(len(brief.factual_claims), 2)

    def test_brief_with_cta(self):
        evidence = []
        brief = generate_brief(topic="T", checked_claims=[], evidence=evidence, cta="Subscribe")
        self.assertEqual(brief.cta, "Subscribe")

    def test_key_points_from_claims(self):
        claims = [Claim(claim_id="c1", text="Important fact", topic="t", is_factual=True)]
        evidence = []
        brief = generate_brief(topic="T", checked_claims=claims, evidence=evidence)
        self.assertIn("Important fact", brief.key_points)

    def test_non_factual_claims_in_key_points(self):
        claims = [Claim(claim_id="c1", text="Opinion", topic="t", is_factual=False)]
        evidence = []
        brief = generate_brief(topic="T", checked_claims=claims, evidence=evidence)
        self.assertIn("Opinion", brief.key_points)
