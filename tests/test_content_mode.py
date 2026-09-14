"""Tests for content generation modes."""
import unittest
from core.content_mode import build_content_from_brief, ContentMode
from core.briefing import ContentBrief
from core.claims import Claim
from core.evidence import Evidence


class TestAutoMode(unittest.TestCase):
    def test_auto_uses_brief_key_points(self):
        claims = (Claim(claim_id="c1", text="AI is growing", topic="AI", is_factual=True),)
        evidence = (Evidence(source_url="https://a.com", source_title="A", publisher="P", extracted_text="AI growing fast"),)
        brief = ContentBrief(
            topic="AI", audience="general", platform="youtube_long",
            format="video", angle="informative",
            key_points=("AI grows",), factual_claims=claims, supporting_evidence=evidence,
        )
        result = build_content_from_brief(brief, mode=ContentMode.AUTO)
        self.assertEqual(result["mode"], "AUTO")
        self.assertIn("AI grows", result["key_points"])


class TestCustomMode(unittest.TestCase):
    def test_custom_uses_provided_key_points(self):
        brief = ContentBrief(
            topic="AI", audience="general", platform="youtube_long",
            format="video", angle="informative",
            key_points=("AI grows",),
        )
        custom_kp = ("Custom point", "Another point")
        result = build_content_from_brief(
            brief, mode=ContentMode.CUSTOM, custom_key_points=custom_kp,
        )
        self.assertEqual(result["mode"], "CUSTOM")
        self.assertEqual(result["key_points"], custom_kp)

    def test_custom_falls_back_to_brief(self):
        brief = ContentBrief(
            topic="AI", audience="general", platform="youtube_long",
            format="video", angle="informative",
            key_points=("AI grows",),
        )
        result = build_content_from_brief(brief, mode=ContentMode.CUSTOM)
        self.assertEqual(result["key_points"], ("AI grows",))


class TestHybridMode(unittest.TestCase):
    def test_hybrid_merges_brief_and_custom(self):
        brief = ContentBrief(
            topic="AI", audience="general", platform="youtube_long",
            format="video", angle="informative",
            key_points=("Brief point",),
        )
        custom_kp = ("Custom point",)
        result = build_content_from_brief(
            brief, mode=ContentMode.HYBRID, custom_key_points=custom_kp,
        )
        self.assertEqual(result["mode"], "HYBRID")
        self.assertIn("Brief point", result["key_points"])
        self.assertIn("Custom point", result["key_points"])

    def test_hybrid_dedupes(self):
        brief = ContentBrief(
            topic="AI", audience="general", platform="youtube_long",
            format="video", angle="informative",
            key_points=("Same point",),
        )
        result = build_content_from_brief(
            brief, mode=ContentMode.HYBRID, custom_key_points=("Same point",),
        )
        self.assertEqual(result["key_points"], ("Same point",))

    def test_hybrid_preserves_claims(self):
        claims = (Claim(claim_id="c1", text="Claim", topic="t"),)
        brief = ContentBrief(
            topic="AI", audience="general", platform="youtube_long",
            format="video", angle="informative",
            factual_claims=claims,
        )
        result = build_content_from_brief(brief, mode=ContentMode.HYBRID)
        self.assertEqual(result["factual_claims"], claims)


class TestModeFromBrief(unittest.TestCase):
    def test_preserves_source_references(self):
        evidence = (Evidence(source_url="https://a.com", source_title="A", publisher="P", extracted_text="text"),)
        brief = ContentBrief(
            topic="AI", audience="general", platform="youtube_long",
            format="video", angle="informative",
            supporting_evidence=evidence,
        )
        result = build_content_from_brief(brief, mode=ContentMode.AUTO)
        self.assertIn("https://a.com", result["source_references"])
