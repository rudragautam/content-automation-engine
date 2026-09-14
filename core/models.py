"""Domain models for the News + Trends Engine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str
    published_at: str | None = None
    content: str = ""
    category: str = ""
    raw: dict | None = None


@dataclass(frozen=True)
class TrendItem:
    keyword: str
    score: float
    trend_direction: str
    region: str
    raw: dict | None = None


@dataclass(frozen=True)
class StoryCluster:
    story_id: str
    items: tuple["NewsItem", ...]
    keywords: tuple[str, ...]
    importance_score: float
    source_density: dict[str, int]
