"""Conservative story clustering using normalized title token Jaccard similarity.

Limitation: This is token-overlap clustering, not semantic clustering.
Unrelated stories sharing common words (e.g., "the", "and") may be grouped.
Without an LLM, true semantic clustering is not feasible.
The similarity_threshold parameter (default 0.5) mitigates but does not eliminate false merges.
"""

import re
from typing import List

from core.models import NewsItem, StoryCluster


def _tokenize(title: str) -> set[str]:
    return set(re.findall(r"[a-z]+", title.lower()))


def _jaccard(tokens1: set[str], tokens2: set[str]) -> float:
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    if not union:
        return 0.0
    return len(intersection) / len(union)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx = self.find(x)
        ry = self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def groups(self) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            root = self.find(i)
            if root not in groups:
                groups[root] = []
            groups[root].append(i)
        return groups


def cluster(items: List[NewsItem], similarity_threshold: float = 0.5) -> List[StoryCluster]:
    if not items:
        return []

    tokenized = [_tokenize(item.title) for item in items]
    n = len(items)
    uf = _UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            sim = _jaccard(tokenized[i], tokenized[j])
            if sim >= similarity_threshold:
                uf.union(i, j)

    groups = uf.groups()
    clusters: List[StoryCluster] = []
    for idx, (root, indices) in enumerate(groups.items()):
        sorted_indices = sorted(indices)
        cluster_items = tuple(items[i] for i in sorted_indices)
        all_keywords: set[str] = set()
        for i in sorted_indices:
            all_keywords.update(tokenized[i])
        source_density: dict[str, int] = {}
        for i in sorted_indices:
            source_density[items[i].source] = source_density.get(items[i].source, 0) + 1
        clusters.append(
            StoryCluster(
                story_id=f"cluster-{idx}",
                items=cluster_items,
                keywords=tuple(sorted(all_keywords)),
                importance_score=0.0,
                source_density=source_density,
            )
        )

    return clusters
