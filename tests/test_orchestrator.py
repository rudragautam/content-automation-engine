"""Tests for engine orchestrator."""
import unittest
import os
import json
import tempfile
import shutil

from core.run_config import RunConfig
from core.content_mode import ContentMode
from core.orchestrator import EngineOrchestrator
from templates.registry import TemplateRegistry
from templates.adapters.registry import TemplateAdapterRegistry
from templates.adapters.base import TemplateAdapter
from templates.metadata import TemplateMetadata
from templates.exceptions import TemplateUnavailableError, TemplateNotFoundError

FUNCTIONAL_TEMPLATES = [
    "01_Focus_Habits_Shorts_9x16",
    "02_Geeta_Gyaan_9x16",
    "03_General_Quiz_9x16",
    "04_Science_Quiz_9x16",
    "05_Science_Storytelling_9x16",
    "06_Indian_Traditional_Story_9x16",
    "07_Indian_Heritage_Story_16x9",
    "08_Crime_Files_16x9",
    "14_AI_Neural_Intelligence_16x9",
    "15_AI_Digital_Future_16x9",
]


class TestOrchestratorCustom(unittest.TestCase):
    def test_custom_mode_populates_template(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test Topic",
            key_points=("Point 1", "Point 2"),
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
            template_id="02_Geeta_Gyaan_9x16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        self.assertTrue(os.path.isfile(result["populated_html"]))
        self.assertTrue(os.path.isfile(result["manifest"]))
        self.assertTrue(os.path.isfile(result["content"]))
        self.assertTrue(os.path.isfile(result["assets"]))

    def test_custom_mode_uses_user_content(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="My Topic",
            key_points=("Key Point 1", "Key Point 2"),
            template_id="01_Focus_Habits_Shorts_9x16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        with open(result["populated_html"], "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Key Point 1", html)
        self.assertIn("Key Point 2", html)

    def test_custom_mode_no_fabrication(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="My Topic",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        with open(result["content"], "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["topic"], "My Topic")


class TestOrchestratorAuto(unittest.TestCase):
    def test_auto_mode_runs(self):
        config = RunConfig(
            mode=ContentMode.AUTO,
            topic="Auto Topic",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
            template_id="01_Focus_Habits_Shorts_9x16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        self.assertTrue(os.path.isfile(result["populated_html"]))


class TestOrchestratorHybrid(unittest.TestCase):
    def test_hybrid_mode_runs(self):
        config = RunConfig(
            mode=ContentMode.HYBRID,
            topic="Hybrid Topic",
            key_points=("Research Point",),
            storyline=("User Point",),
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
            template_id="01_Focus_Habits_Shorts_9x16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        with open(result["content"], "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("Hybrid Topic", data["topic"])


class TestOrchestratorTemplateSelection(unittest.TestCase):
    def test_template_by_id(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            template_id="02_Geeta_Gyaan_9x16",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        self.assertEqual(result["template_id"], "02_Geeta_Gyaan_9x16")

    def test_template_by_filename(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            template_filename="02_Geeta_Gyaan_9x16.html",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])

    def test_missing_template_error(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            template_id="99_Nonexistent_Template",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertFalse(result["success"])
        self.assertTrue(any("template" in e.lower() for e in result["errors"]))

    def test_stub_template_unavailable(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="09_Finance_Base_16x9",
            name="Finance Base",
            format="youtube_long",
            aspect_ratio="16:9",
            adapter_id="long_16x9",
            available=False,
            source_path="templates/09_Finance_Base_16x9.html",
        ))
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            template_id="09_Finance_Base_16x9",
            platform="youtube_long",
            content_format="youtube_long",
            aspect_ratio="16:9",
        )
        result = EngineOrchestrator(
            config=config,
            template_registry=reg,
        ).run()
        self.assertFalse(result["success"])


class TestOrchestratorByTemplateType(unittest.TestCase):
    def test_shorts_template(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Shorts Test",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])

    def test_story_template(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Story Test",
            key_points=("Point 1",),
            template_id="07_Indian_Heritage_Story_16x9",
            platform="youtube_long",
            content_format="youtube_long",
            aspect_ratio="16:9",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])

    def test_quiz_template(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Quiz Test",
            key_points=("Point 1",),
            template_id="03_General_Quiz_9x16",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])

    def test_16x9_template(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="16:9 Test",
            key_points=("Point 1",),
            template_id="08_Crime_Files_16x9",
            platform="youtube_long",
            content_format="youtube_long",
            aspect_ratio="16:9",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])

    def test_ai_template(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="AI Test",
            key_points=("Point 1",),
            template_id="14_AI_Neural_Intelligence_16x9",
            platform="youtube_long",
            content_format="youtube_long",
            aspect_ratio="16:9",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])


class TestOrchestratorAssets(unittest.TestCase):
    def test_asset_assignment(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            key_points=("Point 1",),
            template_id="02_Geeta_Gyaan_9x16",
            assets={"bg": "/assets/bg.png"},
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        with open(result["assets"], "r") as f:
            assets_data = json.load(f)
        self.assertIn("bg", assets_data)
        self.assertEqual(assets_data["bg"]["path"], "/assets/bg.png")

    def test_invalid_asset_path(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
            assets={"bad": "/nonexistent/path.png"},
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        with open(result["assets"], "r") as f:
            assets_data = json.load(f)
        self.assertIn("warnings", assets_data["bad"])
        self.assertTrue(len(assets_data["bad"]["warnings"]) > 0)


class TestOrchestratorTheme(unittest.TestCase):
    def test_theme_populated(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
            theme={"bg": "#ff0000", "accent": "#00ff00"},
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        with open(result["populated_html"], "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("--bg:#ff0000", html)
        self.assertIn("--accent:#00ff00", html)

    def test_no_theme_preserves_original(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertTrue(result["success"])
        with open(result["populated_html"], "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn("var(--bg)", html)


class TestOrchestratorOutputStructure(unittest.TestCase):
    def test_output_has_all_files(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
            output_dir="output/runs",
        )
        result = EngineOrchestrator(config=config).run()
        for path in [result["populated_html"], result["manifest"], result["content"], result["assets"]]:
            self.assertTrue(os.path.isfile(path), f"{path} missing")

    def test_output_has_run_id_dir(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
            output_dir="output/runs",
        )
        result = EngineOrchestrator(config=config).run()
        self.assertIn(result["run_id"], result["output_dir"])
        self.assertTrue(os.path.isdir(result["output_dir"]))


class TestOrchestratorManifest(unittest.TestCase):
    def test_manifest_has_required_fields(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test Topic",
            key_points=("Point 1",),
            template_id="01_Focus_Habits_Shorts_9x16",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
            output_dir="output/runs",
        )
        result = EngineOrchestrator(config=config).run()
        with open(result["manifest"], "r") as f:
            manifest = json.load(f)
        required = ["run_id", "timestamp", "mode", "content_format", "platform",
                    "aspect_ratio", "template_id", "topic", "assets", "theme", "output_path"]
        for field in required:
            self.assertIn(field, manifest, f"Missing field: {field}")
        self.assertEqual(manifest["template_id"], "01_Focus_Habits_Shorts_9x16")

    def test_manifest_from_run_result(self):
        from core.manifest import Manifest
        config = RunConfig(mode=ContentMode.CUSTOM, topic="Test")
        manifest = Manifest.from_run_result(
            run_id="abc123",
            config=config,
            output_path="output/test/populated.html",
        )
        d = manifest.to_dict()
        self.assertEqual(d["run_id"], "abc123")
        self.assertEqual(d["mode"], "CUSTOM")
        self.assertIn("timestamp", d)
