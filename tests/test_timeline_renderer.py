"""Tests for TimelineRenderer: frame count and video length follow slide durations."""
import os
import shutil
import tempfile
import unittest

from rendering.timeline_renderer import TimelineRenderer
from rendering.video_encoder import FFmpegEncoder

TWO_SLIDE_PAGE = """<!DOCTYPE html><html><body style="margin:0">
<div id="s" style="width:100%;height:100vh;background:#000"></div>
<script>
const colors=["#f00","#00f"];
window.__engine={count:2,goTo(i){document.getElementById("s").style.background=colors[i]}};
</script></body></html>"""


def chromium_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@unittest.skipUnless(chromium_available(), "Playwright Chromium not installed")
class TestTimelineRenderer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_frames_and_duration_match_plan(self):
        renderer = TimelineRenderer(aspect_ratio="1:1", fps=10)
        frames = renderer.capture(TWO_SLIDE_PAGE, [0.5, 1.0], os.path.join(self.tmp, "frames"))
        self.assertEqual(len(frames), 15)

        encoder = FFmpegEncoder(fps=10)
        video = encoder.encode_frames(frames, os.path.join(self.tmp, "out.mp4"), renderer.width, renderer.height)
        result = encoder.validate(video, expected_width=1080, expected_height=1080, expected_duration=1.5)
        self.assertTrue(result["valid"], result)

    def test_slide_count_mismatch(self):
        renderer = TimelineRenderer(aspect_ratio="1:1", fps=10)
        with self.assertRaises(RuntimeError):
            renderer.capture(TWO_SLIDE_PAGE, [1.0], os.path.join(self.tmp, "frames"))

    def test_template_without_engine_hook(self):
        renderer = TimelineRenderer(aspect_ratio="1:1", fps=10)
        with self.assertRaises(RuntimeError):
            renderer.capture("<html><body></body></html>", [1.0], os.path.join(self.tmp, "frames"))


if __name__ == "__main__":
    unittest.main()
