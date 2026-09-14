from dataclasses import dataclass
from typing import Any, List

@dataclass(frozen=True)
class PipelineContext:
    payload: Any

class ContentAutomationPipeline:
    def run(self, context: PipelineContext) -> PipelineContext:
        return context

class NewsTrendsPipeline:
    def __init__(self, news_providers: List, trends_providers: List):
        self._news_providers = news_providers
        self._trends_providers = trends_providers

    def run(self, context: PipelineContext) -> PipelineContext:
        from core.deduplication import deduplicate
        from core.clustering import cluster
        from core.scoring import compute_importance, compute_source_density

        all_news: List = []
        for provider in self._news_providers:
            try:
                items = provider.fetch()
                all_news.extend(items)
            except Exception:
                pass

        deduped = deduplicate(all_news)
        source_density = compute_source_density(deduped)
        clusters = cluster(deduped)
        enriched_clusters = []
        for idx, cl in enumerate(clusters):
            importance = compute_importance(cl.items[0], deduped) if cl.items else 0.0
            enriched_clusters.append(
                type(cl)(
                    story_id=cl.story_id,
                    items=cl.items,
                    keywords=cl.keywords,
                    importance_score=importance,
                    source_density=source_density,
                )
            )

        all_trends = []
        for provider in self._trends_providers:
            try:
                items = provider.fetch()
                all_trends.extend(items)
            except Exception:
                pass

        enriched = {
            "news": deduped,
            "clusters": clusters,
            "trends": all_trends,
        }
        return PipelineContext(payload=enriched)

class ResearchContentPipeline:
    def __init__(self, news_trends_pipeline, research_providers, fact_check, brief_generator, content_generator):
        self._news_trends_pipeline = news_trends_pipeline
        self._research_providers = research_providers
        self._fact_check = fact_check
        self._brief_generator = brief_generator
        self._content_generator = content_generator

    def run(self, context: PipelineContext) -> PipelineContext:
        from core.claims import Claim
        from core.normalization import deduplicate_sources, normalize_sources

        context = self._news_trends_pipeline.run(context)
        payload = dict(context.payload) if context.payload else {}

        all_news = list(payload.get("news", []))

        all_evidence = []
        for provider in self._research_providers:
            try:
                for item in all_news:
                    topic = getattr(item, "title", str(item))
                    evidence = provider.fetch(topic)
                    all_evidence.extend(evidence)
            except Exception:
                pass

        all_evidence = deduplicate_sources(normalize_sources(all_evidence))
        payload["evidence"] = all_evidence

        claims = [
            Claim(claim_id=f"claim-{i}", text=getattr(item, "title", str(item)), topic=getattr(item, "title", str(item)))
            for i, item in enumerate(all_news)
        ]
        checked_claims = self._fact_check(claims, all_evidence)
        payload["checked_claims"] = checked_claims

        brief = self._brief_generator(
            topic=payload.get("topic", "Research Summary"),
            checked_claims=checked_claims,
            evidence=all_evidence,
        )
        payload["content_brief"] = brief

        content = self._content_generator.generate(brief)
        payload["content"] = content

        return PipelineContext(payload=payload)


class ContentTemplatePipeline:
    def __init__(
        self,
        research_pipeline,
        asset_validator=None,
        template_registry=None,
        template_populator=None,
        renderer=None,
    ):
        self._research_pipeline = research_pipeline
        self._asset_validator = asset_validator
        self._template_registry = template_registry
        self._template_populator = template_populator
        self._renderer = renderer

    def run(self, context: PipelineContext) -> PipelineContext:
        from core.content import (
            ShortsContent,
            LongFormContent,
            SocialContent,
            CarouselContent,
            Scene,
            Slide,
            Chapter,
            Section,
        )
        from core.content_mode import build_content_from_brief, ContentMode

        context = self._research_pipeline.run(context)
        payload = dict(context.payload) if context.payload else {}

        content_item = payload.get("content")
        brief = payload.get("content_brief")
        checked_claims = payload.get("checked_claims", ())
        evidence = payload.get("evidence", [])

        if content_item is None or brief is None:
            payload["render_html"] = ""
            payload["render_ready"] = False
            return PipelineContext(payload=payload)

        platform = brief.platform
        format_str = brief.format

        content_format = self._build_content_format(
            content_item, brief, platform, format_str, checked_claims, evidence,
        )
        payload["content_format"] = content_format

        assets = payload.get("assets", [])
        validated_assets = self._validate_assets(assets)
        payload["validated_assets"] = validated_assets

        assigned_content = self._assign_assets(content_format, validated_assets)
        payload["assigned_content"] = assigned_content

        template_result = self._select_and_populate_template(
            assigned_content, validated_assets, payload,
        )
        payload["render_html"] = template_result.get("html", "")
        payload["template_used"] = template_result.get("template_id", "")
        payload["render_ready"] = bool(template_result.get("html"))

        return PipelineContext(payload=payload)

    def _build_content_format(
        self, content_item, brief, platform, format_str, claims, evidence
    ):
        common = {
            "content_id": getattr(content_item, "brief_id", "content-001"),
            "title": getattr(content_item, "title", brief.topic),
            "source_references": tuple(ev.source_url for ev in evidence),
            "factual_claims": tuple(claims),
            "provenance": {
                "method": "deterministic",
                "evidence_sources": tuple(ev.source_url for ev in evidence),
            },
        }

        if platform in ("youtube_short",) or format_str == "short_video":
            return ShortsContent(
                **common,
                hook=getattr(content_item, "body", brief.topic)[:200],
                intro="",
                scenes=(Scene(scene_id="s1", title=brief.topic, text=getattr(content_item, "body", ""), narration=""),),
                cta=brief.cta,
            )
        elif platform in ("youtube_long",) or format_str == "long_video":
            return LongFormContent(
                **common,
                hook=getattr(content_item, "body", brief.topic)[:200],
                intro=f"Introduction to {brief.topic}",
                chapters=(Chapter(chapter_id="c1", title=brief.topic, sections=(Section(section_id="sec1", title="Overview", text=getattr(content_item, "body", ""), narration=""),), narration=""),),
                cta=brief.cta,
            )
        elif platform in ("social_post",) or format_str == "post":
            return SocialContent(
                **common,
                hook=brief.key_points[0] if brief.key_points else brief.topic,
                body=getattr(content_item, "body", brief.topic),
                cta=brief.cta,
                metadata={"platform": platform, "format": format_str},
            )
        elif platform in ("carousel",) or format_str == "carousel":
            slides = ()
            for i, kp in enumerate(brief.key_points):
                slides = slides + (Slide(slide_id=f"slide-{i}", title=f"Point {i+1}", body=kp),)
            return CarouselContent(
                **common,
                cover=Slide(slide_id="cover", title=brief.topic, body=brief.angle) if brief.angle else None,
                slides=slides,
                cta=brief.cta,
            )
        else:
            return SocialContent(
                **common,
                hook=brief.topic,
                body=getattr(content_item, "body", brief.topic),
                cta=brief.cta,
            )

    def _validate_assets(self, assets):
        if not assets or self._asset_validator is None:
            return assets
        validated = []
        for asset in assets:
            try:
                result = self._asset_validator.validate(asset)
                if result.valid:
                    validated.append((asset, result))
                else:
                    validated.append((asset, result))
            except Exception:
                validated.append((asset, None))
        return validated

    def _assign_assets(self, content_format, validated_assets):
        if not validated_assets:
            return content_format
        return content_format

    def _select_and_populate_template(self, content, assets, payload):
        from templates.registry import TemplateRegistry
        from templates.populator import TemplatePopulator
        from templates.exceptions import (
            TemplateUnavailableError,
            TemplateIncompatibleError,
        )

        template_id = ""
        html = ""

        if self._template_registry is not None and content is not None:
            try:
                aspect = self._get_aspect_ratio(content)
                fmt = getattr(content, "platform", "")
                if not fmt:
                    fmt = getattr(content, "format", "")
                metadata = self._template_registry.select(
                    platform=fmt,
                    aspect_ratio=aspect,
                    content_format=fmt,
                )
                template_id = metadata.template_id

                if not metadata.available:
                    raise TemplateUnavailableError(
                        f"Template '{template_id}' is registered but not yet available."
                    )

                from templates.loader import TemplateLoader
                loader = TemplateLoader()
                try:
                    html_content, _ = loader.load(template_id)
                except (TemplateUnavailableError, FileNotFoundError):
                    html = self._build_placeholder_html(content, assets, template_id)
                else:
                    populator = self._template_populator or TemplatePopulator()
                    data = self._build_template_data(content, assets)
                    html = populator.populate(html_content, data=data)

            except (TemplateUnavailableError, TemplateIncompatibleError, FileNotFoundError):
                html = self._build_placeholder_html(content, assets, template_id)

        return {"html": html, "template_id": template_id}

    def _get_aspect_ratio(self, content):
        platform = getattr(content, "platform", "")
        if platform in ("youtube_short",):
            return "9:16"
        if platform in ("youtube_long",):
            return "16:9"
        if platform in ("social_post",):
            return "1:1"
        if platform in ("carousel",):
            return "1:1"
        return "16:9"

    def _build_template_data(self, content, assets):
        data = {
            "title": getattr(content, "title", ""),
            "hook": getattr(content, "hook", ""),
            "body": getattr(content, "body", "") if hasattr(content, "body") else "",
            "cta": getattr(content, "cta", "") or "",
            "content_id": getattr(content, "content_id", ""),
        }
        for ev in getattr(content, "factual_claims", ()):
            data[f"claim_{getattr(ev, 'claim_id', '')}"] = getattr(ev, "text", "")
        return data

    def _build_placeholder_html(self, content, assets, template_id):
        title = getattr(content, "title", "Content")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 1rem; }}
h1 {{ font-size: 1.5rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="content" data-template="{template_id}">
<p>Content format: {getattr(content, 'platform', '')} / {getattr(content, 'format', '')}</p>
</div>
</body>
</html>"""
