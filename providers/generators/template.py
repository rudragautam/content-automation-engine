"""Deterministic template-based content generator (fallback)."""

import logging
import uuid
from typing import List

from core.briefing import ContentBrief, ContentItem
from core.specs import get_spec
from providers.generators.base import ContentGenerator

logger = logging.getLogger(__name__)


class TemplateContentGenerator(ContentGenerator):
    def generate(self, brief: ContentBrief) -> ContentItem:
        spec = get_spec(brief.platform, brief.format)
        title = self._render_title(brief)
        body = self._render_body(brief, spec)
        claims = tuple(brief.factual_claims) if brief.factual_claims else ()
        evidence_urls = self._extract_evidence_urls(brief.supporting_evidence)
        return ContentItem(
            title=title,
            body=body,
            claims=claims,
            evidence_urls=evidence_urls,
            platform=brief.platform,
            format=brief.format,
            brief_id=str(uuid.uuid4())[:8],
        )

    def _render_title(self, brief: ContentBrief) -> str:
        return f"{brief.topic}: {brief.angle}"

    def _render_body(self, brief: ContentBrief, spec) -> str:
        parts = []
        for section in spec.structure:
            section_content = self._render_section(section, brief)
            if section_content:
                parts.append(f"## {section}\n{section_content}")
        return "\n\n".join(parts)

    def _render_section(self, section: str, brief: ContentBrief) -> str:
        if section == "hook":
            return self._render_hook(brief)
        elif section == "intro":
            return f"Introduction to {brief.topic}"
        elif section == "key_points":
            return "\n".join(f"- {kp}" for kp in brief.key_points)
        elif section == "deep_dive":
            return self._render_deep_dive(brief)
        elif section == "summary":
            return self._render_summary(brief)
        elif section == "key_facts":
            return "\n".join(f"- {kp}" for kp in brief.key_points)
        elif section == "cta":
            return brief.cta if brief.cta else ""
        elif section == "title":
            return self._render_title(brief)
        elif section == "points":
            return "\n".join(f"- {kp}" for kp in brief.key_points)
        elif section == "conclusion":
            return f"Conclusion on {brief.topic}"
        elif section == "intro":
            return f"Introduction to {brief.topic}"
        return ""

    def _render_hook(self, brief: ContentBrief) -> str:
        if brief.key_points:
            return f"Did you know? {brief.key_points[0]}"
        return f"Exploring {brief.topic}"

    def _render_deep_dive(self, brief: ContentBrief) -> str:
        parts = []
        for claim in brief.factual_claims:
            parts.append(f"Claim: {claim.text}")
        for ev in brief.supporting_evidence:
            parts.append(f"Source: {ev.source_title} ({ev.source_url})")
        return "\n".join(parts) if parts else f"More on {brief.topic}"

    def _render_summary(self, brief: ContentBrief) -> str:
        return f"Summary: {brief.topic} — {brief.angle}"

    def _extract_evidence_urls(self, evidence) -> tuple:
        urls = []
        for ev in evidence:
            url = getattr(ev, "source_url", "")
            if url:
                urls.append(url)
        return tuple(urls)
