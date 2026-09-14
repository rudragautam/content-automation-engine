"""Tests for deterministic fact-check logic."""
import unittest
from core.claims import Claim
from core.evidence import Evidence
from core.factcheck import fact_check, _jaccard, _tokenize, _contains_negation


class TestTokenize(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_tokenize("Hello World"), {"hello", "world"})

    def test_case_insensitive(self):
        self.assertEqual(_tokenize("HELLO world"), {"hello", "world"})

    def test_strips_punctuation(self):
        self.assertEqual(_tokenize("Hello, World!"), {"hello", "world"})

    def test_short_words_filtered(self):
        result = _tokenize("I am a test")
        self.assertNotIn("i", result)
        self.assertNotIn("a", result)
        self.assertIn("am", result)
        self.assertIn("test", result)


class TestContainsNegation(unittest.TestCase):
    def test_negation_present(self):
        self.assertTrue(_contains_negation("This is not true"))

    def test_no_negation(self):
        self.assertFalse(_contains_negation("This is true"))

    def test_debunk(self):
        self.assertTrue(_contains_negation("Scientists debunk the theory"))


class TestJaccard(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(_jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_no_overlap(self):
        self.assertEqual(_jaccard({"a"}, {"b"}), 0.0)

    def test_partial(self):
        self.assertAlmostEqual(_jaccard({"a", "b", "c"}, {"b", "c", "d"}), 2/4)


class TestFactCheck(unittest.TestCase):
    def test_supported_claim(self):
        claim = Claim(claim_id="c1", text="AI technology advances", topic="AI")
        evidence = [Evidence(
            source_url="https://example.com",
            source_title="AI Advances Report",
            publisher="Tech News",
            extracted_text="AI technology has made significant advances in recent years",
        )]
        results = fact_check([claim], evidence)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].classification, "supported")
        self.assertGreater(results[0].confidence, 0.0)

    def test_insufficient_evidence(self):
        claim = Claim(claim_id="c1", text="Quantum computing breakthrough", topic="quantum")
        evidence = [Evidence(
            source_url="https://example.com",
            source_title="Cooking Tips",
            publisher="Food Network",
            extracted_text="How to make the perfect omelette",
        )]
        results = fact_check([claim], evidence)
        self.assertEqual(results[0].classification, "insufficient_evidence")

    def test_conflicting_claim(self):
        claim = Claim(claim_id="c1", text="Solar energy is efficient", topic="energy")
        evidence = [Evidence(
            source_url="https://example.com",
            source_title="Energy Report",
            publisher="Science Daily",
            extracted_text="Solar energy is not efficient compared to wind power",
        )]
        results = fact_check([claim], evidence)
        self.assertEqual(results[0].classification, "conflicting")

    def test_conflicting_wins_over_supporting(self):
        claim = Claim(claim_id="c1", text="Battery technology improved", topic="tech")
        supporting = Evidence(
            source_url="https://good.com",
            source_title="Battery News",
            publisher="Tech",
            extracted_text="Battery technology has improved significantly this year",
        )
        conflicting = Evidence(
            source_url="https://bad.com",
            source_title="Battery Critique",
            publisher="Review",
            extracted_text="Battery technology is not improved and remains unreliable",
        )
        results = fact_check([claim], [supporting, conflicting])
        self.assertEqual(results[0].classification, "conflicting")

    def test_no_evidence(self):
        claim = Claim(claim_id="c1", text="Test claim", topic="test")
        results = fact_check([claim], [])
        self.assertEqual(results[0].classification, "insufficient_evidence")
        self.assertEqual(results[0].confidence, 0.0)

    def test_multiple_claims(self):
        claims = [
            Claim(claim_id="c1", text="AI advances", topic="AI"),
            Claim(claim_id="c2", text="Space exploration", topic="space"),
        ]
        evidence = [Evidence(
            source_url="https://a.com", source_title="AI News", publisher="P",
            extracted_text="AI advances in machine learning",
        )]
        results = fact_check(claims, evidence)
        self.assertEqual(results[0].classification, "supported")
        self.assertEqual(results[1].classification, "insufficient_evidence")


class TestConfidenceCalculation(unittest.TestCase):
    def test_zero_confidence_no_evidence(self):
        claim = Claim(claim_id="c1", text="Test", topic="t")
        results = fact_check([claim], [])
        self.assertEqual(results[0].confidence, 0.0)

    def test_high_confidence_multiple_sources(self):
        claim = Claim(claim_id="c1", text="AI technology", topic="AI")
        evidence = [
            Evidence(source_url="https://a.com", source_title="A", publisher="P1",
                     extracted_text="AI technology advances"),
            Evidence(source_url="https://b.com", source_title="B", publisher="P2",
                     extracted_text="AI technology progress"),
        ]
        results = fact_check([claim], evidence)
        self.assertGreater(results[0].confidence, 0.3)

    def test_confidence_is_bounded(self):
        claim = Claim(claim_id="c1", text="AI", topic="AI")
        evidence = []
        for i in range(10):
            evidence.append(Evidence(
                source_url=f"https://s{i}.com", source_title=f"S{i}", publisher=f"P{i}",
                extracted_text="AI technology is great",
            ))
        results = fact_check([claim], evidence)
        self.assertGreaterEqual(results[0].confidence, 0.0)
        self.assertLessEqual(results[0].confidence, 1.0)


class TestProvenance(unittest.TestCase):
    def test_provenance_attached(self):
        claim = Claim(claim_id="c1", text="Test", topic="t")
        evidence = [Evidence(source_url="https://a.com", source_title="A", publisher="P",
                             extracted_text="Test evidence")]
        results = fact_check([claim], evidence)
        self.assertIsNotNone(results[0].provenance)
        self.assertIn("method", results[0].provenance)
        self.assertIn("source_urls", results[0].provenance)
        self.assertIn("supporting_count", results[0].provenance)

    def test_source_urls_preserved(self):
        claim = Claim(claim_id="c1", text="Test", topic="t")
        evidence = [
            Evidence(source_url="https://a.com", source_title="A", publisher="P",
                     extracted_text="Test evidence"),
            Evidence(source_url="https://b.com", source_title="B", publisher="P",
                     extracted_text="More evidence"),
        ]
        results = fact_check([claim], evidence)
        self.assertIn("https://a.com", results[0].provenance["source_urls"])
        self.assertIn("https://b.com", results[0].provenance["source_urls"])
