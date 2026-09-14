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
