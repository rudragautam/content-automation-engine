"""Tests for template selection and compatibility."""
import unittest
from templates.registry import TemplateRegistry
from templates.metadata import TemplateMetadata
from templates.exceptions import (
    TemplateUnavailableError,
    TemplateIncompatibleError,
)
from templates.loader import TemplateLoader
from templates.adapter import TemplateAdapter
from templates.populator import TemplatePopulator
import tempfile
import os


class TestTemplateSelection(unittest.TestCase):
    def test_select_shorts_9x16(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="sh1", name="Shorts", format="youtube_short",
            aspect_ratio="9:16", adapter_id="shorts_9x16", available=True,
        ))
        result = reg.select(platform="youtube_short", aspect_ratio="9:16")
        self.assertEqual(result.template_id, "sh1")

    def test_select_long_16x9(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="lf1", name="Long", format="youtube_long",
            aspect_ratio="16:9", adapter_id="long_16x9", available=True,
        ))
        result = reg.select(platform="youtube_long", aspect_ratio="16:9")
        self.assertEqual(result.template_id, "lf1")

    def test_select_prefers_available(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="a1", name="Avail", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=True,
        ))
        reg.register(TemplateMetadata(
            template_id="a2", name="Unavail", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=False,
        ))
        result = reg.select(platform="youtube_long", aspect_ratio="16:9")
        self.assertEqual(result.template_id, "a1")


class TestFormatCompatibility(unittest.TestCase):
    def test_shorts_9x16_compatible(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="sh1", name="Shorts", format="youtube_short",
            aspect_ratio="9:16", adapter_id="shorts_9x16", available=True,
            supported_content_types=("youtube_short",),
        ))
        result = reg.validate_compatibility("sh1", "youtube_short", "9:16")
        self.assertTrue(result["compatible"])

    def test_shorts_16x9_incompatible_aspect(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="sh1", name="Shorts", format="youtube_short",
            aspect_ratio="9:16", adapter_id="shorts_9x16", available=True,
        ))
        result = reg.validate_compatibility("sh1", "youtube_short", "16:9")
        self.assertFalse(result["aspect_match"])


class TestTemplatePopulationEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.loader = TemplateLoader(templates_dir=self.temp_dir)
        self.registry = TemplateRegistry()
        self.registry.register(TemplateMetadata(
            template_id="e2e", name="E2E", format="youtube_long",
            aspect_ratio="16:9", adapter_id="long_16x9", available=True,
            source_path=os.path.join(self.temp_dir, "e2e.html"),
        ))
        with open(os.path.join(self.temp_dir, "e2e.html"), "w") as f:
            f.write('<html><title>{{title}}</title><body>{{content}}</body></html>')

    def test_populate_with_content(self):
        from templates.registry import TemplateRegistry
        from templates.populator import TemplatePopulator
        populator = TemplatePopulator()
        html, meta = self.loader.load("e2e")
        data = {"title": "Test Title", "content": "Test Content"}
        result = populator.populate(html, data)
        self.assertIn("Test Title", result)
        self.assertIn("Test Content", result)

    def test_unavailable_template_handling(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="una", name="Unavail", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=False,
        ))
        # select will raise TemplateUnavailableError
        with self.assertRaises(TemplateUnavailableError):
            reg.select(platform="youtube_long", aspect_ratio="16:9")
