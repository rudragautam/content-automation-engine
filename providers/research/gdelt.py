"""GDELT research provider."""

import json
import logging
import urllib.request
import urllib.parse
from typing import Any, Dict, List

from core.evidence import Evidence
from providers.research.base import ResearchProvider

logger = logging.getLogger(__name__)


class GDELTResearchProvider(ResearchProvider):
    def __init__(self, query_url: str, params: Dict[str, str]):
        self._query_url = query_url
        self._params = params

    def fetch(self, topic: str) -> List[Evidence]:
        try:
            return self._fetch(topic)
        except Exception as e:
            logger.error("GDELT research fetch failed: %s", e)
            return []

    def _fetch(self, topic: str) -> List[Evidence]:
        params = dict(self._params)
        params["query"] = topic
        url = self._build_url(params)
        logger.info("Fetching GDELT research from %s", url)
        req = urllib.request.Request(url, headers={"User-Agent": "ContentAutomationEngine/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return self._parse(data, topic)

    def _build_url(self, params: Dict[str, str]) -> str:
        query_string = urllib.parse.urlencode(params)
        return f"{self._query_url}?{query_string}"

    def _parse(self, data: Dict[str, Any], topic: str) -> List[Evidence]:
        evidence: List[Evidence] = []
        articles = data.get("articles", data.get("items", []))
        if not isinstance(articles, list):
            logger.warning("GDELT research response does not contain a list")
            return []
        for article in articles:
            title = article.get("title", "")
            url = article.get("url", article.get("link", ""))
            source = article.get("source", article.get("site", "GDELT"))
            text = article.get("summary", article.get("description", ""))
            published = article.get("published", article.get("date", None))
            evidence.append(
                Evidence(
                    source_url=url,
                    source_title=title,
                    publisher=source,
                    published_at=published,
                    extracted_text=text,
                )
            )
        return evidence
