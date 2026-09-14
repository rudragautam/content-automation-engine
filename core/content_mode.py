"""Content generation modes: AUTO, CUSTOM, HYBRID."""

from enum import Enum


class ContentMode(str, Enum):
    AUTO = "AUTO"
    CUSTOM = "CUSTOM"
    HYBRID = "HYBRID"


def build_content_from_brief(
    brief,
    mode: ContentMode = ContentMode.AUTO,
    custom_key_points: Tuple[str, ...] = (),
    custom_storyline: str = "",
) -> dict:
    topic = brief.topic
    platform = brief.platform
    format_str = brief.format
    angle = brief.angle
    tone = brief.tone
    language = brief.language
    cta = brief.cta

    if mode == ContentMode.CUSTOM:
        key_points = custom_key_points if custom_key_points else brief.key_points
    elif mode == ContentMode.HYBRID:
        hybrid_points = list(brief.key_points) + list(custom_key_points)
        key_points = tuple(dict.fromkeys(hybrid_points))
    else:
        key_points = brief.key_points

    content_type = format_str if format_str else platform
    return {
        "topic": topic,
        "platform": platform,
        "format": format_str,
        "angle": angle,
        "tone": tone,
        "language": language,
        "key_points": key_points,
        "cta": cta,
        "mode": mode.value,
        "custom_storyline": custom_storyline,
        "factual_claims": tuple(brief.factual_claims) if brief.factual_claims else (),
        "supporting_evidence": tuple(brief.supporting_evidence) if brief.supporting_evidence else (),
        "source_references": tuple(ev.source_url for ev in brief.supporting_evidence) if brief.supporting_evidence else (),
    }
