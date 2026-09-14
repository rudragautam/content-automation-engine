"""Claim models for fact checking."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    topic: str
    is_factual: bool = True


@dataclass(frozen=True)
class CheckedClaim:
    claim_id: str
    text: str
    topic: str
    classification: str
    confidence: float
    evidence: tuple = ()
    supporting_evidence_urls: tuple = ()
    contradicting_evidence_urls: tuple = ()
    provenance: dict | None = None
