"""RSS news provider."""

import logging
from typing import List

import feedparser

from core.models import NewsItem
from providers.news.base import NewsProvider

logger = logging.getLogger(__name__)


class RSSNewsProvider(NewsProvider):
    def __init__(self, feed_urls: list[str]):
        self._feed_urls = feed_urls

    def fetch(self) -> List[NewsItem]:
        items: List[NewsItem] = []
        for url in self._feed_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    items.append(
                        NewsItem(
                            title=getattr(entry, "title", ""),
                            url=getattr(entry, "link", ""),
                            source=url,
                            published_at=getattr(entry, "published", None),
                            content=getattr(entry, "summary", ""),
                            raw=entry.get("summary_detail", {}) if hasattr(entry, "get") else {},
                        )
                    )
            except Exception as e:
                logger.error("RSS fetch failed for %s: %s", url, e)
        return items
