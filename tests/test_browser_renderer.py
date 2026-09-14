"""Tests for BrowserRenderer."""
import unittest
import os
import json
import tempfile
import shutil

from rendering.browser_renderer import BrowserRenderer, get_viewport_dimensions


class TestViewportDimensions(unittest.TestCase):
    def test_9_16(self):
        self.assertEqual(get_viewport_dimensions("9:16"), (1080, 1920))

    def test_16_9(self):
        self.assertEqual(get_viewport_dimensions("16:9"), (1920, 1080))

    def test_1_1(self):
        self.assertEqual(get_viewport_dimensions("1:1"), (1080, 1080))

    def test_invalid_aspect(self):
        with self.assertRaises(ValueError):
            get_viewport_dimensions("4:3")


class TestBrowserRendererInit(unittest.TestCase):
    def test_default_9_16(self):
        r = BrowserRenderer(aspect_ratio="9:16")
        self.assertEqual(r.width, 1080)
        self.assertEqual(r.height, 1920)
        self.assertEqual(r.aspect_ratio, "9:16")

    def test_explicit_dimensions(self):
        r = BrowserRenderer(width=1920, height=1080)
        self.assertEqual(r.width, 1920)
        self.assertEqual(r.height, 1080)

    def test_invalid_both_missing(self):
        with self.assertRaises(ValueError):
            BrowserRenderer()


class TestBrowserRendererRender(unittest.TestCase):
    def test_render_9_16_template(self):
        html = """<!DOCTYPE html><html><head><style>:root{--bg:#000}:root{--accent:#fff}</style></head><body><div>Test</div><script>document.body.innerHTML+='<p>Hello</p>';</script></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            renderer = BrowserRenderer(aspect_ratio="9:16", headless=True)
            result = renderer.render(
                html_content=html,
                output_dir=tmp,
                duration=2.0,
                scene_count=3,
            )
            self.assertEqual(result["frame_count"], 3)
            self.assertEqual(result["width"], 1080)
            self.assertEqual(result["height"], 1920)
            for fp in result["frame_paths"]:
                self.assertTrue(os.path.isfile(fp))
                self.assertGreater(os.path.getsize(fp), 0)
            renderer.close()

    def test_render_16_9_template(self):
        html = """<!DOCTYPE html><html><head></head><body><div>16:9</div></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            renderer = BrowserRenderer(aspect_ratio="16:9", headless=True)
            result = renderer.render(
                html_content=html,
                output_dir=tmp,
                duration=1.0,
                scene_count=2,
            )
            self.assertEqual(result["frame_count"], 2)
            self.assertEqual(result["width"], 1920)
            self.assertEqual(result["height"], 1080)
            renderer.close()

    def test_render_single_screenshot(self):
        html = "<html><body><h1>Hello</h1></body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            renderer = BrowserRenderer(aspect_ratio="9:16", headless=True)
            path = os.path.join(tmp, "screenshot.png")
            result = renderer.render_single(html_content=html, output_path=path)
            self.assertTrue(os.path.isfile(result))
            self.assertGreater(os.path.getsize(result), 0)
            renderer.close()

    def test_no_browser_raises(self):
        import rendering.browser_renderer as br
        original = br.Playwright
        br.Playwright = None
        try:
            renderer = BrowserRenderer(aspect_ratio="9:16")
            with self.assertRaises(RuntimeError) as cm:
                renderer._ensure_browser()
            self.assertIn("Playwright", str(cm.exception))
        finally:
            br.Playwright = original
