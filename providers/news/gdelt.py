"""GDELT news provider using the DOC 2.0 API."""

import json
import logging
import urllib.request
import urllib.parse
from typing import Any, Dict, List

from core.models import NewsItem
from providers.news.base import NewsProvider

logger = logging.getLogger(__name__)


class GDELTNewsProvider(NewsProvider):
    def __init__(self, query_url: str, params: Dict[str, str]):
        self._query_url = query_url
        self._params = params

    def fetch(self) -> List[NewsItem]:
        try:
            return self._fetch_articles()
        except Exception as e:
            logger.error("GDELT fetch failed: %s", e)
            return []

    def _fetch_articles(self) -> List[NewsItem]:
        url = self._build_url()
        logger.info("Fetching GDELT from %s", url)
        req = urllib.request.Request(url, headers={"User-Agent": "ContentAutomationEngine/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return self._parse_articles(data)

    def _build_url(self) -> str:
        query_string = urllib.parse.urlencode(self._params)
        return f"{self._query_url}?{query_string}"

    def _parse_articles(self, data: Dict[str, Any]) -> List[NewsItem]:
        items: List[NewsItem] = []
        articles = data.get("articles", data.get("items", []))
        if not isinstance(articles, list):
            logger.warning("GDELT response does not contain a list of articles: %s", type(articles))
            return []
        for article in articles:
            title = article.get("title", "")
            url = article.get("url", article.get("link", ""))
            source = article.get("source", article.get("site", ""))
            content = article.get("summary", article.get("description", ""))
            published = article.get("published", article.get("date", None))
            items.append(
                NewsItem(
                    title=title,
                    url=url,
                    source=source,
                    published_at=published,
                    content=content,
                    raw=article,
                )
            )
        return items
