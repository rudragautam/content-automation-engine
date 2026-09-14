"""Tests for template adapter."""
import unittest
from templates.adapter import TemplateAdapter


class TestTemplateAdapter(unittest.TestCase):
    def test_map_content(self):
        adapter = TemplateAdapter(
            adapter_id="test",
            mappings={
                "title": "tpl_title",
                "body": "tpl_content",
            },
        )
        content = {"title": "My Title", "body": "My Body", "extra": "ignored"}
        result = adapter.map_content(content)
        self.assertEqual(result["tpl_title"], "My Title")
        self.assertEqual(result["tpl_content"], "My Body")

    def test_map_content_missing_fields(self):
        adapter = TemplateAdapter(
            adapter_id="test",
            mappings={"title": "tpl_title"},
        )
        content = {}
        result = adapter.map_content(content)
        self.assertEqual(result["tpl_title"], "")

    def test_map_asset(self):
        adapter = TemplateAdapter(adapter_id="test")
        asset = {"asset_id": "a1", "path": "/img.png", "type": "image"}
        result = adapter.map_asset(asset, role="background")
        self.assertEqual(result["asset_id"], "a1")
        self.assertEqual(result["path"], "/img.png")
        self.assertEqual(result["role"], "background")
        self.assertEqual(result["type"], "image")

    def test_map_theme_with_supported_fields(self):
        adapter = TemplateAdapter(adapter_id="test")
        theme = {"accent": "red", "bg": "blue", "ignored": "x"}
        result = adapter.map_theme(theme, supported_fields=("accent",))
        self.assertEqual(result, {"accent": "red"})

    def test_map_theme_no_supported_fields(self):
        adapter = TemplateAdapter(adapter_id="test")
        theme = {"accent": "red"}
        result = adapter.map_theme(theme, supported_fields=())
        self.assertEqual(result, {})
