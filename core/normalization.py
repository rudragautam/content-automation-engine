"""Source URL normalization and deduplication for research sources."""

import re
from typing import List

from core.evidence import Evidence


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/").lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def normalize_source(ev: Evidence) -> Evidence:
    return Evidence(
        source_url=normalize_url(ev.source_url),
        source_title=ev.source_title.strip(),
        publisher=ev.publisher.strip(),
        published_at=ev.published_at,
        extracted_text=ev.extracted_text,
        retrieved_at=ev.retrieved_at,
    )


def normalize_sources(evidence_list: List[Evidence]) -> List[Evidence]:
    return [normalize_source(ev) for ev in evidence_list]


def deduplicate_sources(evidence_list: List[Evidence]) -> List[Evidence]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: List[Evidence] = []
    for ev in evidence_list:
        url = normalize_url(ev.source_url)
        title = re.sub(r"[^\w\s]", "", ev.source_title.lower()).strip()
        if url in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        seen_urls.add(url)
        if title:
            seen_titles.add(title)
        result.append(ev)
    return result
