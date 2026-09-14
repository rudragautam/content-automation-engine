"""Story importance and source-density scoring."""

from typing import List

from core.models import NewsItem


def compute_importance(item: NewsItem, all_items: List[NewsItem]) -> float:
    score = 1.0
    source_count = sum(1 for i in all_items if i.source == item.source)
    if source_count == 1:
        score += 0.5
    return score


def compute_source_density(items: List[NewsItem]) -> dict[str, int]:
    density: dict[str, int] = {}
    for item in items:
        density[item.source] = density.get(item.source, 0) + 1
    return density
