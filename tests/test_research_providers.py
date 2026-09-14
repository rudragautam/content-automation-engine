"""Tests for research provider failure isolation."""
import unittest
from unittest.mock import MagicMock, patch
from core.evidence import Evidence
from core.models import NewsItem
from providers.research.rss import RSSResearchProvider
from providers.research.gdelt import GDELTResearchProvider


class TestRSSResearchProvider(unittest.TestCase):
    @patch("providers.research.rss.feedparser")
    def test_fetch_returns_evidence(self, mock_feedparser):
        entry = MagicMock()
        entry.title = "AI Breakthrough"
        entry.link = "https://example.com/ai"
        entry.summary = "AI technology breakthrough today"
        mock_feedparser.parse.return_value.entries = [entry]

        provider = RSSResearchProvider(["https://example.com/feed"])
        result = provider.fetch("AI")

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Evidence)
        self.assertEqual(result[0].source_title, "AI Breakthrough")
        self.assertEqual(result[0].source_url, "https://example.com/ai")

    @patch("providers.research.rss.feedparser")
    def test_fetch_topic_filtering(self, mock_feedparser):
        relevant = MagicMock()
        relevant.title = "AI News"
        relevant.link = "https://a.com"
        relevant.summary = "AI breakthrough"

        irrelevant = MagicMock()
        irrelevant.title = "Sports"
        irrelevant.link = "https://b.com"
        irrelevant.summary = "Game results"

        mock_feedparser.parse.return_value.entries = [relevant, irrelevant]

        provider = RSSResearchProvider(["https://example.com/feed"])
        result = provider.fetch("AI")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source_title, "AI News")

    @patch("providers.research.rss.feedparser")
    def test_fetch_partial_on_error(self, mock_feedparser):
        good_entry = MagicMock()
        good_entry.title = "Test News"
        good_entry.link = "https://good.com"
        good_entry.summary = "Test content about the topic"

        def side_effect(url):
            if "bad" in url:
                raise Exception("network error")
            feed_mock = MagicMock()
            feed_mock.entries = [good_entry]
            return feed_mock

        mock_feedparser.parse.side_effect = side_effect

        provider = RSSResearchProvider(["https://good.com/feed", "https://bad.com/feed"])
        result = provider.fetch("test")
        self.assertEqual(len(result), 1)

    @patch("providers.research.rss.feedparser")
    def test_fetch_empty_on_all_failures(self, mock_feedparser):
        mock_feedparser.parse.side_effect = Exception("all fail")
        provider = RSSResearchProvider(["https://fail.com/feed"])
        result = provider.fetch("test")
        self.assertEqual(result, [])


class TestGDELTResearchProvider(unittest.TestCase):
    @patch("providers.research.gdelt.urllib.request.urlopen")
    def test_fetch_returns_evidence(self, mock_urlopen):
        import json
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"articles": [{"title": "GDELT Story", "url": "https://gdelt.com", "source": "GDELT"}]}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = GDELTResearchProvider(
            query_url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": "test", "timespan": "24H", "mode": "ArtList", "format": "json"},
        )
        result = provider.fetch("United States")
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Evidence)
        self.assertEqual(result[0].source_title, "GDELT Story")

    @patch("providers.research.gdelt.urllib.request.urlopen")
    def test_fetch_partial_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("timeout")
        provider = GDELTResearchProvider(
            query_url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": "test", "timespan": "24H", "mode": "ArtList", "format": "json"},
        )
        result = provider.fetch("test")
        self.assertEqual(result, [])


class TestResearchProviderFailureIsolation(unittest.TestCase):
    def test_failing_provider_does_not_crash(self):
        class FailingProvider:
            def fetch(self, topic):
                raise Exception("provider down")

        from core.factcheck import fact_check
        from core.briefing import generate_brief
        from providers.generators.template import TemplateContentGenerator

        failing = FailingProvider()
        gen = TemplateContentGenerator()
        generator = gen  # use as content_generator

        from core.pipeline import NewsTrendsPipeline, ResearchContentPipeline, PipelineContext

        class FakeNewsItem:
            def __init__(self, title):
                self.title = title
                self.url = f"https://{title}.com"
                self.source = "test"

        news_pipeline = NewsTrendsPipeline(
            news_providers=[],
            trends_providers=[],
        )

        research_pipeline = ResearchContentPipeline(
            news_trends_pipeline=news_pipeline,
            research_providers=[FailingProvider()],
            fact_check=fact_check,
            brief_generator=generate_brief,
            content_generator=gen,
        )

        ctx = PipelineContext(payload={})
        result = research_pipeline.run(ctx)
        self.assertIsNotNone(result)
        self.assertIn("evidence", result.payload)
        self.assertEqual(result.payload["evidence"], [])


class TestResearchProviderInterface(unittest.TestCase):
    def test_rss_provider_has_fetch(self):
        from providers.research.rss import RSSResearchProvider
        provider = RSSResearchProvider(["https://example.com/feed"])
        self.assertTrue(hasattr(provider, "fetch"))

    def test_gdelt_provider_has_fetch(self):
        from providers.research.gdelt import GDELTResearchProvider
        provider = GDELTResearchProvider(
            query_url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": "test"},
        )
        self.assertTrue(hasattr(provider, "fetch"))
