"""Integration tests for NewsTrendsPipeline and Phase 1 preservation."""

import unittest
import importlib
import inspect
import sys

from core.pipeline import ContentAutomationPipeline, PipelineContext, NewsTrendsPipeline
from core.models import NewsItem, TrendItem
from config.markets.us import US_MARKET


class TestContentAutomationPipelinePreserved(unittest.TestCase):
    def test_existing_pipeline_still_works(self):
        from core.pipeline import ContentAutomationPipeline, PipelineContext
        context = PipelineContext(payload={"status": "ready"})
        result = ContentAutomationPipeline().run(context)
        self.assertEqual(result, context)


class TestNewsTrendsPipeline(unittest.TestCase):
    def test_pipeline_with_working_providers(self):
        news_provider = self._make_news_provider([
            NewsItem(title="Story A", url="https://a.com", source="src1"),
            NewsItem(title="Story B", url="https://b.com", source="src2"),
        ])
        trends_provider = self._make_trends_provider([
            TrendItem(keyword="AI", score=95.0, trend_direction="up", region="US"),
        ])
        pipeline = NewsTrendsPipeline(news_providers=[news_provider], trends_providers=[trends_provider])
        context = PipelineContext(payload={})
        result = pipeline.run(context)

        self.assertIn("news", result.payload)
        self.assertIn("clusters", result.payload)
        self.assertIn("trends", result.payload)
        self.assertEqual(len(result.payload["news"]), 2)
        self.assertEqual(len(result.payload["trends"]), 1)

    def test_pipeline_with_failing_providers(self):
        class FailingNewsProvider:
            def fetch(self):
                raise Exception("provider down")

        class FailingTrendsProvider:
            def fetch(self):
                raise Exception("trends down")

        pipeline = NewsTrendsPipeline(
            news_providers=[FailingNewsProvider()],
            trends_providers=[FailingTrendsProvider()],
        )
        context = PipelineContext(payload={})
        result = pipeline.run(context)

        self.assertIn("news", result.payload)
        self.assertIn("clusters", result.payload)
        self.assertIn("trends", result.payload)
        self.assertEqual(result.payload["news"], [])
        self.assertEqual(result.payload["clusters"], [])
        self.assertEqual(result.payload["trends"], [])

    def test_pipeline_does_not_crash_on_mixed_failure(self):
        class FailingNewsProvider:
            def fetch(self):
                raise Exception("down")

        class FailingTrendsProvider:
            def fetch(self):
                raise Exception("trends down")

        news_provider = self._make_news_provider([
            NewsItem(title="Story", url="https://s.com", source="src"),
        ])
        pipeline = NewsTrendsPipeline(
            news_providers=[FailingNewsProvider(), news_provider],
            trends_providers=[FailingTrendsProvider()],
        )
        context = PipelineContext(payload={})
        result = pipeline.run(context)
        self.assertEqual(len(result.payload["news"]), 1)

    def test_pipeline_returns_pipeline_context(self):
        pipeline = NewsTrendsPipeline(news_providers=[], trends_providers=[])
        context = PipelineContext(payload={"original": True})
        result = pipeline.run(context)
        self.assertIsInstance(result, PipelineContext)

    @staticmethod
    def _make_news_provider(items):
        class MockNewsProvider:
            def fetch(self):
                return list(items)
        return MockNewsProvider()

    @staticmethod
    def _make_trends_provider(items):
        class MockTrendsProvider:
            def fetch(self):
                return list(items)
        return MockTrendsProvider()


class TestUSMarketDefaults(unittest.TestCase):
    def test_region_is_us(self):
        self.assertEqual(US_MARKET.region, "US")

    def test_google_trends_url_has_geo_us(self):
        self.assertIn("geo=US", US_MARKET.google_trends_rss_url)

    def test_gdelt_query_url_is_set(self):
        self.assertEqual(
            US_MARKET.gdelt_query_url,
            "https://api.gdeltproject.org/api/v2/doc/doc",
        )

    def test_gdelt_params_are_explicit(self):
        self.assertIsNotNone(US_MARKET.gdelt_params)
        self.assertEqual(US_MARKET.gdelt_params["query"], "United States")
        self.assertEqual(US_MARKET.gdelt_params["format"], "json")

    def test_rss_feed_urls_are_configured(self):
        self.assertGreater(len(US_MARKET.rss_feed_urls), 0)


class TestCoreHasNoProviderOrConfigImports(unittest.TestCase):
    def test_core_modules_have_no_provider_imports(self):
        core_dir = "core"
        provider_imports = []
        for filename in ["models.py", "deduplication.py", "clustering.py", "scoring.py", "pipeline.py"]:
            with open(f"{core_dir}/{filename}") as f:
                content = f.read()
            if "from providers" in content or "import providers" in content:
                provider_imports.append(filename)
        self.assertEqual(
            provider_imports,
            [],
            f"Core modules have provider imports: {provider_imports}",
        )

    def test_core_modules_have_no_config_imports(self):
        core_dir = "core"
        config_imports = []
        for filename in ["models.py", "deduplication.py", "clustering.py", "scoring.py", "pipeline.py"]:
            with open(f"{core_dir}/{filename}") as f:
                content = f.read()
            if "from config" in content or "import config" in content:
                config_imports.append(filename)
        self.assertEqual(
            config_imports,
            [],
            f"Core modules have config imports: {config_imports}",
        )

    def test_news_trends_pipeline_does_not_import_providers(self):
        source = inspect.getsource(NewsTrendsPipeline)
        self.assertNotIn("from providers", source)
        self.assertNotIn("import providers", source)


class TestPhase1TestsStillPass(unittest.TestCase):
    def test_smoke_test_imports(self):
        import tests.test_smoke
        self.assertTrue(hasattr(tests.test_smoke, "PipelineSmokeTest"))


if __name__ == "__main__":
    unittest.main()
