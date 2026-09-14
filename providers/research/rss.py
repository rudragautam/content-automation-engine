"""RSS research provider."""

import logging
from typing import List

import feedparser

from core.evidence import Evidence
from providers.research.base import ResearchProvider

logger = logging.getLogger(__name__)


class RSSResearchProvider(ResearchProvider):
    def __init__(self, feed_urls: list[str]):
        self._feed_urls = feed_urls

    def fetch(self, topic: str) -> List[Evidence]:
        evidence: List[Evidence] = []
        for url in self._feed_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    title = getattr(entry, "title", "")
                    if topic.lower() in title.lower() or topic.lower() in getattr(entry, "summary", "").lower():
                        evidence.append(
                            Evidence(
                                source_url=getattr(entry, "link", ""),
                                source_title=title,
                                publisher=url,
                                published_at=getattr(entry, "published", None),
                                extracted_text=getattr(entry, "summary", ""),
                            )
                        )
            except Exception as e:
                logger.error("RSS research fetch failed for %s: %s", url, e)
        return evidence
