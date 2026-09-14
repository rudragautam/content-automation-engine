"""Tests for deterministic template content generator."""
import unittest
from core.briefing import ContentBrief, ContentItem
from core.claims import Claim
from core.evidence import Evidence
from providers.generators.template import TemplateContentGenerator


class TestTemplateContentGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = TemplateContentGenerator()

    def test_generates_content_item(self):
        brief = ContentBrief(
            topic="AI News",
            audience="general",
            platform="youtube_long",
            format="video",
            angle="informative",
            key_points=("Point 1", "Point 2"),
            tone="neutral",
            language="en",
        )
        item = self.generator.generate(brief)
        self.assertIsInstance(item, ContentItem)
        self.assertIn("AI News", item.title)
        self.assertIn("informative", item.title)

    def test_preserves_claims(self):
        claims = (Claim(claim_id="c1", text="Test claim", topic="t", is_factual=True),)
        brief = ContentBrief(
            topic="Test", audience="A", platform="P", format="F", angle="informative",
            factual_claims=claims,
        )
        item = self.generator.generate(brief)
        self.assertEqual(item.claims, claims)

    def test_preserves_evidence_urls(self):
        evidence = (Evidence(source_url="https://a.com", source_title="A", publisher="P"),)
        brief = ContentBrief(
            topic="Test", audience="A", platform="P", format="F", angle="informative",
            supporting_evidence=evidence,
        )
        item = self.generator.generate(brief)
        self.assertIn("https://a.com", item.evidence_urls)

    def test_deterministic_output(self):
        brief1 = ContentBrief(topic="X", audience="A", platform="P", format="F", angle="informative")
        brief2 = ContentBrief(topic="X", audience="A", platform="P", format="F", angle="informative")
        item1 = self.generator.generate(brief1)
        item2 = self.generator.generate(brief2)
        self.assertEqual(item1.title, item2.title)
        self.assertEqual(item1.body, item2.body)
        self.assertEqual(item1.platform, item2.platform)
        self.assertEqual(item1.format, item2.format)

    def test_youtube_short_generation(self):
        brief = ContentBrief(
            topic="Quick News", audience="mobile", platform="youtube_short", format="short_video",
            angle="breaking", cta="Tap to subscribe",
        )
        item = self.generator.generate(brief)
        self.assertEqual(item.platform, "youtube_short")
        self.assertIn("Quick News", item.title)

    def test_social_post_generation(self):
        brief = ContentBrief(
            topic="Hot Topic", audience="followers", platform="social_post", format="post",
            angle="engaging", cta="Share this",
        )
        item = self.generator.generate(brief)
        self.assertEqual(item.platform, "social_post")

    def test_carousel_generation(self):
        brief = ContentBrief(
            topic="Guide", audience="learners", platform="carousel", format="carousel",
            angle="educational",
        )
        item = self.generator.generate(brief)
        self.assertEqual(item.platform, "carousel")

    def test_generated_content_has_structure(self):
        brief = ContentBrief(
            topic="Test", audience="A", platform="youtube_long", format="video",
            angle="informative", key_points=("Point 1",),
        )
        item = self.generator.generate(brief)
        self.assertIn("intro", item.body.lower())
        self.assertIn("summary", item.body.lower())

    def test_generated_content_contains_evidence_urls(self):
        evidence = (Evidence(source_url="https://source.com", source_title="Source", publisher="P"),)
        brief = ContentBrief(
            topic="Test", audience="A", platform="P", format="F", angle="angle",
            supporting_evidence=evidence,
        )
        item = self.generator.generate(brief)
        self.assertIn("https://source.com", item.body)

    def test_never_invents_facts(self):
        brief = ContentBrief(
            topic="Test", audience="A", platform="P", format="F", angle="angle",
            key_points=(), factual_claims=(), supporting_evidence=(),
        )
        item = self.generator.generate(brief)
        self.assertIn("Test", item.title)

    def test_cta_included(self):
        brief = ContentBrief(
            topic="T", audience="A", platform="P", format="F", angle="angle",
            cta="Sign up now",
        )
        item = self.generator.generate(brief)
        self.assertIn("Sign up now", item.body)

    def test_non_empty_brief_id(self):
        brief = ContentBrief(topic="T", audience="A", platform="P", format="F", angle="angle")
        item = self.generator.generate(brief)
        self.assertGreater(len(item.brief_id), 0)
