"""News deduplication by URL and title similarity."""

import re
from typing import List

from core.models import NewsItem


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def _normalize_title(title: str) -> str:
    return re.sub(r"[^\w\s]", "", title.lower()).strip()


def deduplicate(items: List[NewsItem]) -> List[NewsItem]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: List[NewsItem] = []
    for item in items:
        norm_url = _normalize_url(item.url)
        norm_title = _normalize_title(item.title)
        if norm_url in seen_urls:
            continue
        if norm_title and norm_title in seen_titles:
            continue
        seen_urls.add(norm_url)
        if norm_title:
            seen_titles.add(norm_title)
        result.append(item)
    return result
