"""Unit tests for providers."""
import json
import unittest
from unittest.mock import MagicMock, patch

from core.models import NewsItem, TrendItem
from providers.news.rss import RSSNewsProvider
from providers.news.gdelt import GDELTNewsProvider
from providers.trends.google_trends_rss import GoogleTrendsRSSProvider


class TestRSSNewsProvider(unittest.TestCase):
    @patch("providers.news.rss.feedparser")
    def test_fetch_returns_news_items(self, mock_feedparser):
        mock_entry = MagicMock()
        mock_entry.title = "Test Article"
        mock_entry.link = "https://example.com/article"
        mock_entry.published = "2026-01-01T00:00:00Z"
        mock_entry.summary = "Test content"
        mock_feedparser.parse.return_value.entries = [mock_entry]

        provider = RSSNewsProvider(["https://example.com/feed"])
        result = provider.fetch()

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], NewsItem)
        self.assertEqual(result[0].title, "Test Article")
        self.assertEqual(result[0].url, "https://example.com/article")

    @patch("providers.news.rss.feedparser")
    def test_fetch_partial_on_error(self, mock_feedparser):
        mock_entry = MagicMock()
        mock_entry.title = "Good Article"
        mock_entry.link = "https://good.com"
        mock_entry.published = None
        mock_entry.summary = "content"

        def side_effect(url):
            if "bad" in url:
                raise Exception("network error")
            feed_mock = MagicMock()
            feed_mock.entries = [mock_entry]
            return feed_mock

        mock_feedparser.parse.side_effect = side_effect

        provider = RSSNewsProvider(["https://good.com/feed", "https://bad.com/feed"])
        result = provider.fetch()
        self.assertEqual(len(result), 1)

    @patch("providers.news.rss.feedparser")
    def test_fetch_returns_empty_on_all_failures(self, mock_feedparser):
        mock_feedparser.parse.side_effect = Exception("network error")
        provider = RSSNewsProvider(["https://fail.com/feed"])
        result = provider.fetch()
        self.assertEqual(result, [])


class TestGDELTNewsProvider(unittest.TestCase):
    @patch("providers.news.gdelt.urllib.request.urlopen")
    def test_fetch_returns_news_items(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"articles": [{"title": "GDELT Article", "url": "https://gdelt.com/1", "source": "GDELT"}]}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = GDELTNewsProvider(
            query_url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": "test", "timespan": "24H", "mode": "ArtList", "format": "json"},
        )
        result = provider.fetch()

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], NewsItem)
        self.assertEqual(result[0].title, "GDELT Article")

    @patch("providers.news.gdelt.urllib.request.urlopen")
    def test_fetch_partial_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("timeout")
        provider = GDELTNewsProvider(
            query_url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": "test", "timespan": "24H", "mode": "ArtList", "format": "json"},
        )
        result = provider.fetch()
        self.assertEqual(result, [])

    @patch("providers.news.gdelt.urllib.request.urlopen")
    def test_fetch_empty_response(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        provider = GDELTNewsProvider(
            query_url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": "test", "timespan": "24H", "mode": "ArtList", "format": "json"},
        )
        result = provider.fetch()
        self.assertEqual(result, [])

    def test_build_url(self):
        provider = GDELTNewsProvider(
            query_url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": "test", "format": "json"},
        )
        url = provider._build_url()
        self.assertIn("query=test", url)
        self.assertIn("format=json", url)


class TestGoogleTrendsRSSProvider(unittest.TestCase):
    @patch("providers.trends.google_trends_rss.feedparser")
    def test_fetch_returns_trends(self, mock_feedparser):
        mock_entry = MagicMock()
        mock_entry.title = "AI Trending"
        mock_feedparser.parse.return_value.entries = [mock_entry]

        provider = GoogleTrendsRSSProvider("https://trends.google.com/trending/rss?geo=US")
        result = provider.fetch()

        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], TrendItem)
        self.assertEqual(result[0].keyword, "AI Trending")
        self.assertEqual(result[0].region, "US")

    @patch("providers.trends.google_trends_rss.feedparser")
    def test_fetch_returns_empty_on_error(self, mock_feedparser):
        mock_feedparser.parse.side_effect = Exception("network error")
        provider = GoogleTrendsRSSProvider("https://trends.google.com/trending/rss?geo=US")
        result = provider.fetch()
        self.assertEqual(result, [])

    def test_geo_us_in_url(self):
        provider = GoogleTrendsRSSProvider("https://trends.google.com/trending/rss?geo=US")
        self.assertIn("geo=US", provider._rss_url)
