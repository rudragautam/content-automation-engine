"""Tests for VideoOrchestrator."""
import unittest
import os
import json
import tempfile
import shutil

from core.video_orchestrator import VideoOrchestrator
from rendering.video_encoder import FFmpegEncoder
from rendering.browser_renderer import BrowserRenderer


class TestVideoOrchestratorMissingRun(unittest.TestCase):
    def test_missing_populated_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            vor = VideoOrchestrator(run_dir=tmp)
            result = vor.run()
            self.assertFalse(result["success"])

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_path = os.path.join(tmp, "populated.html")
            open(html_path, "w").write("<html></html>")
            vor = VideoOrchestrator(run_dir=tmp)
            result = vor.run()
            self.assertFalse(result["success"])


class TestVideoOrchestratorRealRender(unittest.TestCase):
    def test_real_9_16_render(self):
        from core.orchestrator import EngineOrchestrator
        from core.run_config import RunConfig
        from core.content_mode import ContentMode

        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test Video 9:16",
            key_points=("Point 1", "Point 2", "Point 3"),
            template_id="01_Focus_Habits_Shorts_9x16",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
            output_dir="output/runs",
        )
        orch = EngineOrchestrator(config=config)
        run = orch.run()
        self.assertTrue(run["success"])
        run_dir = run["output_dir"]

        try:
            vor = VideoOrchestrator(
                run_dir=run_dir,
                fps=1,
                duration=2.0,
                scene_count=3,
            )
            result = vor.run()
            self.assertTrue(result["success"], f"Video failed: {result.get('error')}")
            video_path = result["video_path"]
            self.assertTrue(os.path.isfile(video_path))
            self.assertGreater(os.path.getsize(video_path), 0)
            metadata = FFmpegEncoder().validate(video_path, expected_width=1080, expected_height=1920)
            self.assertTrue(metadata["valid"], f"Validation: {metadata}")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_real_16_9_render(self):
        from core.orchestrator import EngineOrchestrator
        from core.run_config import RunConfig
        from core.content_mode import ContentMode

        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test Video 16:9",
            key_points=("Point 1", "Point 2"),
            template_id="15_AI_Digital_Future_16x9",
            platform="youtube_long",
            content_format="youtube_long",
            aspect_ratio="16:9",
            output_dir="output/runs",
        )
        orch = EngineOrchestrator(config=config)
        run = orch.run()
        self.assertTrue(run["success"])
        run_dir = run["output_dir"]

        try:
            vor = VideoOrchestrator(
                run_dir=run_dir,
                fps=1,
                duration=2.0,
                scene_count=3,
            )
            result = vor.run()
            self.assertTrue(result["success"], f"Video failed: {result.get('error')}")
            video_path = result["video_path"]
            self.assertTrue(os.path.isfile(video_path))
            self.assertGreater(os.path.getsize(video_path), 0)
            metadata = FFmpegEncoder().validate(video_path, expected_width=1920, expected_height=1080)
            self.assertTrue(metadata["valid"], f"Validation: {metadata}")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


class TestVideoOrchestratorRendererUnavailable(unittest.TestCase):
    def test_browser_unavailable_error(self):
        import rendering.browser_renderer as br
        original = br.Playwright
        br.Playwright = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                manifest = {"aspect_ratio": "9:16"}
                manifest_path = os.path.join(tmp, "manifest.json")
                with open(manifest_path, "w") as f:
                    json.dump(manifest, f)
                populated = os.path.join(tmp, "populated.html")
                open(populated, "w").write("<html></html>")

                vor = VideoOrchestrator(run_dir=tmp)
                result = vor.run()
                self.assertFalse(result["success"])
                self.assertIn("Browser", result["error"])
        finally:
            br.Playwright = original
