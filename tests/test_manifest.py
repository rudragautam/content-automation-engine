"""Tests for manifest generation."""
import unittest
import os
import json
import tempfile
from core.manifest import Manifest
from core.run_config import RunConfig
from core.content_mode import ContentMode


class TestManifestBasics(unittest.TestCase):
    def test_manifest_creation(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test Topic",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
            template_id="01_Focus_Habits_Shorts_9x16",
            template_filename="01_Focus_Habits_Shorts_9x16.html",
        )
        manifest = Manifest.from_run_result(
            run_id="test-run",
            config=config,
            output_path="output/test/populated.html",
        )
        self.assertEqual(manifest.run_id, "test-run")
        self.assertEqual(manifest.topic, "Test Topic")
        self.assertEqual(manifest.mode, "CUSTOM")
        self.assertEqual(manifest.template_id, "01_Focus_Habits_Shorts_9x16")
        self.assertIsNotNone(manifest.timestamp)
        self.assertEqual(manifest.error, None)

    def test_manifest_with_assets(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            assets={"bg": "/img.png", "logo": "/logo.png"},
        )
        manifest = Manifest.from_run_result(
            run_id="test-run",
            config=config,
            output_path="output/test/populated.html",
        )
        self.assertIn("bg", manifest.assets)
        self.assertEqual(manifest.assets["bg"]["path"], "/img.png")
        self.assertIn("logo", manifest.assets)

    def test_manifest_with_theme(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            theme={"bg": "#ff0000", "accent": "#00ff00"},
        )
        manifest = Manifest.from_run_result(
            run_id="test-run",
            config=config,
            output_path="output/test/populated.html",
        )
        self.assertEqual(manifest.theme["bg"], "#ff0000")
        self.assertEqual(manifest.theme["accent"], "#00ff00")

    def test_manifest_to_json(self):
        config = RunConfig(mode=ContentMode.CUSTOM, topic="Test")
        manifest = Manifest.from_run_result(
            run_id="test-run",
            config=config,
            output_path="output/test/populated.html",
        )
        js = manifest.to_json()
        data = json.loads(js)
        self.assertEqual(data["run_id"], "test-run")
        self.assertIn("timestamp", data)

    def test_manifest_with_error(self):
        config = RunConfig(mode=ContentMode.CUSTOM, topic="Test")
        manifest = Manifest.from_run_result(
            run_id="test-run",
            config=config,
            output_path="output/test/populated.html",
            error="Template not found",
        )
        self.assertEqual(manifest.error, "Template not found")

    def test_manifest_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = RunConfig(mode=ContentMode.CUSTOM, topic="Test")
            manifest = Manifest.from_run_result(
                run_id="test-run",
                config=config,
                output_path=os.path.join(tmpdir, "populated.html"),
            )
            path = manifest.save(tmpdir)
            self.assertTrue(os.path.isfile(path))
            with open(path, "r") as f:
                data = json.load(f)
            self.assertEqual(data["run_id"], "test-run")

    def test_manifest_with_factual_claims(self):
        config = RunConfig(mode=ContentMode.CUSTOM, topic="Test")
        manifest = Manifest.from_run_result(
            run_id="test-run",
            config=config,
            output_path="output/test/populated.html",
            content={
                "topic": "Test",
                "factual_claims": [
                    {"text": "Claim 1", "classification": "supported"},
                    {"text": "Claim 2", "classification": "insufficient_evidence"},
                ],
                "source_references": ["https://example.com"],
            },
        )
        self.assertEqual(len(manifest.factual_claims), 2)
        self.assertIn("Claim 1", manifest.factual_claims)
        self.assertIn("https://example.com", manifest.source_references)
