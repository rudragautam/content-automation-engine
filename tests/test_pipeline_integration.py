"""Pipeline integration tests."""
import unittest
import inspect
from unittest.mock import MagicMock

from core.pipeline import ContentAutomationPipeline, PipelineContext, NewsTrendsPipeline, ResearchContentPipeline
from core.models import NewsItem, TrendItem
from core.evidence import Evidence
from core.claims import Claim
from core.factcheck import fact_check
from core.briefing import generate_brief, ContentBrief
from providers.generators.template import TemplateContentGenerator


class TestPhase1Preserved(unittest.TestCase):
    def test_content_automation_pipeline(self):
        from core.pipeline import ContentAutomationPipeline, PipelineContext
        ctx = PipelineContext(payload={"status": "ready"})
        result = ContentAutomationPipeline().run(ctx)
        self.assertEqual(result, ctx)


class TestPhase2Preserved(unittest.TestCase):
    def test_news_trends_pipeline_unchanged(self):
        news_prov = MagicMock()
        news_prov.fetch.return_value = [NewsItem(title="A", url="U", source="S")]
        trends_prov = MagicMock()
        trends_prov.fetch.return_value = [TrendItem(keyword="K", score=1.0, trend_direction="up", region="US")]
        pipeline = NewsTrendsPipeline(news_providers=[news_prov], trends_providers=[trends_prov])
        ctx = PipelineContext(payload={})
        result = pipeline.run(ctx)
        self.assertIn("news", result.payload)
        self.assertIn("clusters", result.payload)
        self.assertIn("trends", result.payload)
        self.assertEqual(len(result.payload["news"]), 1)


class TestResearchContentPipeline(unittest.TestCase):
    def test_full_pipeline_generates_content(self):
        news_prov = MagicMock()
        news_prov.fetch.return_value = [NewsItem(title="AI Breakthrough", url="https://a.com", source="Tech")]
        trends_prov = MagicMock()
        trends_prov.fetch.return_value = []
        news_pipeline = NewsTrendsPipeline(news_providers=[news_prov], trends_providers=[trends_prov])

        research_prov = MagicMock()
        research_prov.fetch.return_value = [Evidence(
            source_url="https://evidence.com",
            source_title="Evidence Article",
            publisher="Research",
            extracted_text="AI Breakthrough in technology today",
        )]

        gen = TemplateContentGenerator()
        rc_pipeline = ResearchContentPipeline(
            news_trends_pipeline=news_pipeline,
            research_providers=[research_prov],
            fact_check=fact_check,
            brief_generator=generate_brief,
            content_generator=gen,
        )
        ctx = PipelineContext(payload={})
        result = rc_pipeline.run(ctx)
        payload = result.payload
        self.assertIn("news", payload)
        self.assertIn("evidence", payload)
        self.assertIn("checked_claims", payload)
        self.assertIn("content_brief", payload)
        self.assertIn("content", payload)

    def test_pipeline_with_failing_research(self):
        news_prov = MagicMock()
        news_prov.fetch.return_value = [NewsItem(title="Test", url="U", source="S")]
        news_pipeline = NewsTrendsPipeline(news_providers=[news_prov], trends_providers=[])

        class FailingResearch:
            def fetch(self, topic):
                raise Exception("research down")

        gen = TemplateContentGenerator()
        rc_pipeline = ResearchContentPipeline(
            news_trends_pipeline=news_pipeline,
            research_providers=[FailingResearch()],
            fact_check=fact_check,
            brief_generator=generate_brief,
            content_generator=gen,
        )
        ctx = PipelineContext(payload={})
        result = rc_pipeline.run(ctx)
        self.assertIsNotNone(result)
        self.assertIn("evidence", result.payload)

    def test_pipeline_preserves_phase2_news(self):
        news_prov = MagicMock()
        news_prov.fetch.return_value = [
            NewsItem(title="Story A", url="https://a.com", source="S1"),
            NewsItem(title="Story B", url="https://b.com", source="S2"),
        ]
        news_pipeline = NewsTrendsPipeline(news_providers=[news_prov], trends_providers=[])
        gen = TemplateContentGenerator()
        rc_pipeline = ResearchContentPipeline(
            news_trends_pipeline=news_pipeline,
            research_providers=[],
            fact_check=fact_check,
            brief_generator=generate_brief,
            content_generator=gen,
        )
        ctx = PipelineContext(payload={})
        result = rc_pipeline.run(ctx)
        self.assertEqual(len(result.payload["news"]), 2)

    def test_content_has_provenance(self):
        news_prov = MagicMock()
        news_prov.fetch.return_value = [NewsItem(title="Test Story", url="https://s.com", source="Src")]
        news_pipeline = NewsTrendsPipeline(news_providers=[news_prov], trends_providers=[])

        evidence = [Evidence(
            source_url="https://evidence.com",
            source_title="Evidence",
            publisher="Pub",
            extracted_text="Test Story details and facts",
        )]
        research_prov = MagicMock()
        research_prov.fetch.return_value = evidence

        gen = TemplateContentGenerator()
        rc_pipeline = ResearchContentPipeline(
            news_trends_pipeline=news_pipeline,
            research_providers=[research_prov],
            fact_check=fact_check,
            brief_generator=generate_brief,
            content_generator=gen,
        )
        ctx = PipelineContext(payload={})
        result = rc_pipeline.run(ctx)
        checked = result.payload.get("checked_claims", [])
        if checked:
            self.assertIsNotNone(checked[0].provenance)
            self.assertIn("source_urls", checked[0].provenance)

    def test_pipeline_returns_pipeline_context(self):
        news_pipeline = NewsTrendsPipeline(news_providers=[], trends_providers=[])
        gen = TemplateContentGenerator()
        rc_pipeline = ResearchContentPipeline(
            news_trends_pipeline=news_pipeline,
            research_providers=[],
            fact_check=fact_check,
            brief_generator=generate_brief,
            content_generator=gen,
        )
        ctx = PipelineContext(payload={})
        result = rc_pipeline.run(ctx)
        self.assertIsInstance(result, PipelineContext)

    def test_content_claims_preserved(self):
        from core.claims import Claim
        news_prov = MagicMock()
        news_prov.fetch.return_value = [NewsItem(title="Important Claim", url="U", source="S")]
        news_pipeline = NewsTrendsPipeline(news_providers=[news_prov], trends_providers=[])
        gen = TemplateContentGenerator()
        rc_pipeline = ResearchContentPipeline(
            news_trends_pipeline=news_pipeline,
            research_providers=[],
            fact_check=fact_check,
            brief_generator=generate_brief,
            content_generator=gen,
        )
        ctx = PipelineContext(payload={})
        result = rc_pipeline.run(ctx)
        content = result.payload.get("content")
        self.assertIsNotNone(content)
        brief = result.payload.get("content_brief")
        self.assertIsNotNone(brief)
        self.assertEqual(content.claims, brief.factual_claims)
        self.assertTrue(len(content.body) > 0)
        self.assertIn(content.platform, ("youtube_long", "social_post", "carousel", "youtube_short"))


class TestCoreNoProviderImports(unittest.TestCase):
    def test_core_no_provider_imports(self):
        import os
        core_dir = "core"
        for filename in os.listdir(core_dir):
            if filename.endswith(".py"):
                with open(os.path.join(core_dir, filename)) as f:
                    content = f.read()
                self.assertNotIn("from providers", content, f"{filename} has provider import")
                self.assertNotIn("import providers", content, f"{filename} has provider import")

    def test_core_no_config_imports(self):
        import os
        core_dir = "core"
        for filename in os.listdir(core_dir):
            if filename.endswith(".py"):
                with open(os.path.join(core_dir, filename)) as f:
                    content = f.read()
                self.assertNotIn("from config", content, f"{filename} has config import")
                self.assertNotIn("import config", content, f"{filename} has config import")

    def test_news_trends_pipeline_no_provider_imports(self):
        source = inspect.getsource(NewsTrendsPipeline)
        self.assertNotIn("from providers", source)
        self.assertNotIn("import providers", source)

    def test_research_content_pipeline_no_provider_imports_in_core(self):
        source = inspect.getsource(ResearchContentPipeline)
        self.assertNotIn("from providers", source)
        self.assertNotIn("import providers", source)


class TestNoPaidAPIs(unittest.TestCase):
    def test_requirements_no_paid_apis(self):
        with open("requirements.txt") as f:
            content = f.read().lower()
        for api in ["openai", "deepseek", "newsapi", "google.generativeai", "genai", "claude"]:
            self.assertNotIn(api, content)


if __name__ == "__main__":
    unittest.main()
