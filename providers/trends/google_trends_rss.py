"""Google Trends RSS provider."""

import logging
from typing import List

import feedparser

from core.models import TrendItem
from providers.trends.base import TrendsProvider

logger = logging.getLogger(__name__)


class GoogleTrendsRSSProvider(TrendsProvider):
    def __init__(self, rss_url: str, region: str = "US"):
        self._rss_url = rss_url
        self._region = region

    def fetch(self) -> List[TrendItem]:
        try:
            return self._fetch_trends()
        except Exception as e:
            logger.error("Google Trends RSS fetch failed: %s", e)
            return []

    def _fetch_trends(self) -> List[TrendItem]:
        feed = feedparser.parse(self._rss_url)
        trends: List[TrendItem] = []
        for entry in feed.entries:
            title = getattr(entry, "title", "")
            trends.append(
                TrendItem(
                    keyword=title,
                    score=0.0,
                    trend_direction="up",
                    region=self._region,
                    raw=entry.get("summary_detail", {}) if hasattr(entry, "get") else {},
                )
            )
        return trends
