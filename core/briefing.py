"""Content brief model and brief generation from researched content."""

from dataclasses import dataclass
from typing import Optional

from core.claims import Claim
from core.evidence import Evidence


@dataclass(frozen=True)
class ContentItem:
    title: str
    body: str
    claims: tuple = ()
    evidence_urls: tuple = ()
    platform: str = ""
    format: str = ""
    brief_id: str = ""


@dataclass(frozen=True)
class ContentBrief:
    topic: str
    audience: str
    platform: str
    format: str
    angle: str
    key_points: tuple[str, ...] = ()
    factual_claims: tuple = ()
    supporting_evidence: tuple = ()
    tone: str = "neutral"
    language: str = "en"
    cta: Optional[str] = None


def generate_brief(
    topic: str,
    checked_claims,
    evidence,
    audience: str = "general",
    platform: str = "youtube_long",
    format: str = "video",
    angle: str = "informative",
    tone: str = "neutral",
    language: str = "en",
    cta: Optional[str] = None,
) -> ContentBrief:
    key_points = _extract_key_points(checked_claims, evidence)
    return ContentBrief(
        topic=topic,
        audience=audience,
        platform=platform,
        format=format,
        angle=angle,
        key_points=tuple(key_points),
        factual_claims=tuple(checked_claims),
        supporting_evidence=tuple(evidence),
        tone=tone,
        language=language,
        cta=cta,
    )


def _extract_key_points(claims, evidence):
    points = []
    for claim in claims:
        points.append(claim.text)
    for ev in evidence:
        text = ev.extracted_text[:200] if ev.extracted_text else ev.source_title
        if text and text not in points:
            points.append(text)
    return points
