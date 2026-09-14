"""Content format models for Phase 5."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.evidence import Evidence
from core.claims import Claim


@dataclass(frozen=True)
class Scene:
    scene_id: str
    title: str = ""
    text: str = ""
    narration: str = ""
    on_screen_text: str = ""
    duration_ms: Optional[int] = None
    assets: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chapter:
    chapter_id: str
    title: str = ""
    sections: Tuple["Section", ...] = ()
    narration: str = ""


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str = ""
    text: str = ""
    narration: str = ""
    scenes: Tuple[Scene, ...] = ()
    assets: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Slide:
    slide_id: str
    title: str = ""
    body: str = ""
    asset: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CarouselContent:
    content_id: str
    title: str = ""
    hook: str = ""
    cover: Optional[Slide] = None
    slides: Tuple[Slide, ...] = ()
    cta: Optional[str] = None
    source_references: Tuple[str, ...] = ()
    factual_claims: Tuple[Claim, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SocialContent:
    content_id: str
    hook: str = ""
    body: str = ""
    cta: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    template_reference: Optional[str] = None
    source_references: Tuple[str, ...] = ()
    factual_claims: Tuple[Claim, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ShortsContent:
    content_id: str
    title: str = ""
    hook: str = ""
    intro: str = ""
    scenes: Tuple[Scene, ...] = ()
    cta: Optional[str] = None
    source_references: Tuple[str, ...] = ()
    factual_claims: Tuple[Claim, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LongFormContent:
    content_id: str
    title: str = ""
    intro: str = ""
    chapters: Tuple[Chapter, ...] = ()
    sections: Tuple[Section, ...] = ()
    assets: Tuple[str, ...] = ()
    cta: Optional[str] = None
    source_references: Tuple[str, ...] = ()
    factual_claims: Tuple[Claim, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentFormat:
    content_id: str
    platform: str
    format: str
    auto_mode: bool = True
    source_references: Tuple[str, ...] = ()
    factual_claims: Tuple[Claim, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)
