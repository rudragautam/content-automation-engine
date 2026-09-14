"""Platform/format content specifications."""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class PlatformSpec:
    platform: str
    format: str
    max_length: int | None = None
    structure: tuple[str, ...] = ()


@dataclass(frozen=True)
class YouTubeShortSpec(PlatformSpec):
    platform: str = "youtube_short"
    format: str = "short_video"
    max_length: int = 60
    structure: tuple[str, ...] = ("hook", "key_points", "cta")


@dataclass(frozen=True)
class YouTubeLongSpec(PlatformSpec):
    platform: str = "youtube_long"
    format: str = "long_video"
    max_length: int | None = None
    structure: tuple[str, ...] = ("intro", "deep_dive", "summary", "cta")


@dataclass(frozen=True)
class SocialPostSpec(PlatformSpec):
    platform: str = "social_post"
    format: str = "post"
    max_length: int = 280
    structure: tuple[str, ...] = ("hook", "key_facts", "cta")


@dataclass(frozen=True)
class CarouselSpec(PlatformSpec):
    platform: str = "carousel"
    format: str = "carousel"
    max_length: int | None = None
    structure: tuple[str, ...] = ("title", "intro", "points", "conclusion")
    slide_count: int = 5


SPECS: dict[str, PlatformSpec] = {
    "youtube_short": YouTubeShortSpec(),
    "youtube_long": YouTubeLongSpec(),
    "social_post": SocialPostSpec(),
    "carousel": CarouselSpec(),
}


def get_spec(platform: str, format: str = "") -> PlatformSpec:
    key = f"{platform}_{format}" if format else platform
    if key in SPECS:
        return SPECS[key]
    return SPECS.get(platform, SPECS["youtube_long"])
