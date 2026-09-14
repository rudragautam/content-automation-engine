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
