"""Tests for claims models."""
import unittest
from core.claims import Claim, CheckedClaim


class TestClaim(unittest.TestCase):
    def test_create_claim(self):
        claim = Claim(claim_id="c1", text="Test claim", topic="politics", is_factual=True)
        self.assertEqual(claim.claim_id, "c1")
        self.assertEqual(claim.text, "Test claim")
        self.assertEqual(claim.topic, "politics")
        self.assertTrue(claim.is_factual)

    def test_claim_immutable(self):
        claim = Claim(claim_id="c1", text="Test", topic="t")
        with self.assertRaises(AttributeError):
            claim.text = "modified"

    def test_claim_non_factual(self):
        claim = Claim(claim_id="c1", text="Opinion", topic="general", is_factual=False)
        self.assertFalse(claim.is_factual)


class TestCheckedClaim(unittest.TestCase):
    def test_create_checked_claim(self):
        cc = CheckedClaim(
            claim_id="c1",
            text="Test claim",
            topic="politics",
            classification="supported",
            confidence=0.8,
            evidence=(1, 2),
            supporting_evidence_urls=("url1",),
            contradicting_evidence_urls=(),
            provenance={"method": "test"},
        )
        self.assertEqual(cc.classification, "supported")
        self.assertEqual(cc.confidence, 0.8)
        self.assertEqual(cc.supporting_evidence_urls, ("url1",))
        self.assertEqual(cc.contradicting_evidence_urls, ())

    def test_checked_claim_immutable(self):
        cc = CheckedClaim(
            claim_id="c1", text="Test", topic="t",
            classification="supported", confidence=0.5,
        )
        with self.assertRaises(AttributeError):
            cc.classification = "modified"

    def test_default_values(self):
        cc = CheckedClaim(
            claim_id="c1", text="Test", topic="t",
            classification="insufficient_evidence", confidence=0.0,
        )
        self.assertEqual(cc.evidence, ())
        self.assertEqual(cc.supporting_evidence_urls, ())
        self.assertEqual(cc.contradicting_evidence_urls, ())
        self.assertIsNone(cc.provenance)
