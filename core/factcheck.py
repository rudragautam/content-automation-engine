"""Deterministic fact-check logic using evidence token matching.

Classification rules:
- supported: claim tokens significantly overlap with at least one evidence source
  and no evidence contradicts
- conflicting: evidence contains explicit contradiction or opposing facts
- insufficient_evidence: no evidence matches the claim

Confidence is based on evidence quality/coverage, without claiming certainty.
"""

import re
from typing import List, Tuple

from core.claims import Claim, CheckedClaim
from core.evidence import Evidence


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{2,}", text.lower()))


def _contains_negation(text: str) -> bool:
    negations = [
        "not", "no", "never", "neither", "nobody", "nothing", "nowhere",
        "nor", "cannot", "can't", "won't", "wasn't", "weren't", "doesn't",
        "don't", "didn't", "isn't", "aren't", "deny", "denies", "denied",
        "reject", "rejects", "rejected", "disprove", "disproves", "false",
        "incorrect", "untrue", "myth", "rumor", "debunk", "refute", "refutes",
        "refuted", "contradict", "contradicts", "contradicted",
    ]
    words = set(re.findall(r"[a-z]+", text.lower()))
    return any(n in words for n in negations)


def _jaccard(set1: set[str], set2: set[str]) -> float:
    if not set1 or not set2:
        return 0.0
    intersection = set1 & set2
    union = set1 | set2
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _claim_matches_evidence(claim: Claim, evidence: Evidence, threshold: float = 0.1) -> str:
    claim_tokens = _tokenize(claim.text)
    if not claim_tokens:
        return "none"
    evidence_tokens = _tokenize(evidence.extracted_text)
    if not evidence_tokens:
        return "none"
    sim = _jaccard(claim_tokens, evidence_tokens)
    if sim >= threshold:
        if _contains_negation(evidence.extracted_text):
            return "conflicting"
        return "supporting"
    return "none"


def fact_check(claims: List[Claim], evidence_list: List[Evidence]) -> List[CheckedClaim]:
    results: List[CheckedClaim] = []
    for claim in claims:
        supporting: List[Evidence] = []
        contradicting: List[Evidence] = []
        for ev in evidence_list:
            match = _claim_matches_evidence(claim, ev)
            if match == "supporting":
                supporting.append(ev)
            elif match == "conflicting":
                contradicting.append(ev)

        if supporting and not contradicting:
            classification = "supported"
        elif contradicting and not supporting:
            classification = "conflicting"
        elif supporting and contradicting:
            classification = "conflicting"
        else:
            classification = "insufficient_evidence"

        confidence = _calculate_confidence(supporting, contradicting)

        results.append(
            CheckedClaim(
                claim_id=claim.claim_id,
                text=claim.text,
                topic=claim.topic,
                classification=classification,
                confidence=confidence,
                evidence=tuple(supporting + contradicting),
                supporting_evidence_urls=tuple(ev.source_url for ev in supporting),
                contradicting_evidence_urls=tuple(ev.source_url for ev in contradicting),
                provenance={
                    "method": "deterministic_token_match",
                    "evidence_count": len(supporting) + len(contradicting),
                    "supporting_count": len(supporting),
                    "contradicting_count": len(contradicting),
                    "source_urls": tuple(ev.source_url for ev in evidence_list),
                },
            )
        )
    return results


def _calculate_confidence(supporting: List[Evidence], contradicting: List[Evidence]) -> float:
    score = 0.0
    if not supporting and not contradicting:
        return 0.0
    if contradicting:
        score -= 0.4 * len(contradicting)
    if supporting:
        unique_sources = set(ev.source_url for ev in supporting)
        score += 0.2 * len(unique_sources)
        score += 0.1 * len(supporting)
    score = max(0.0, min(1.0, score))
    return round(score, 2)
