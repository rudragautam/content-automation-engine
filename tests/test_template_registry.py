"""Tests for template registry."""
import unittest
from templates.registry import TemplateRegistry
from templates.metadata import TemplateMetadata
from templates.exceptions import (
    TemplateNotFoundError,
    TemplateUnavailableError,
    TemplateIncompatibleError,
)


class TestTemplateRegistry(unittest.TestCase):
    def test_register_and_lookup(self):
        reg = TemplateRegistry()
        meta = TemplateMetadata(
            template_id="test_tpl", name="Test", format="youtube_short",
            aspect_ratio="9:16", adapter_id="shorts_9x16", available=True,
        )
        reg.register(meta)
        result = reg.lookup("test_tpl")
        self.assertEqual(result.template_id, "test_tpl")
        self.assertEqual(result.name, "Test")

    def test_lookup_missing(self):
        reg = TemplateRegistry()
        with self.assertRaises(TemplateNotFoundError):
            reg.lookup("nonexistent")

    def test_list_all(self):
        reg = TemplateRegistry()
        for i in range(3):
            reg.register(TemplateMetadata(
                template_id=f"t{i}", name=f"T{i}", format="youtube_long",
                aspect_ratio="16:9", adapter_id="long_16x9", available=False,
            ))
        self.assertEqual(len(reg.list_all()), 3)

    def test_list_available(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="a1", name="A1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="s", available=True,
        ))
        reg.register(TemplateMetadata(
            template_id="a2", name="A2", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=False,
        ))
        available = reg.list_available()
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0].template_id, "a1")

    def test_filter_by_format(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="s1", name="S1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="s", available=True,
        ))
        reg.register(TemplateMetadata(
            template_id="l1", name="L1", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=True,
        ))
        shorts = reg.filter_by_format("youtube_short")
        self.assertEqual(len(shorts), 1)
        self.assertEqual(shorts[0].format, "youtube_short")

    def test_filter_by_aspect(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="s1", name="S1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="s", available=True,
        ))
        reg.register(TemplateMetadata(
            template_id="l1", name="L1", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=True,
        ))
        results = reg.filter_by_aspect("9:16")
        self.assertEqual(len(results), 1)

    def test_filter_by_adapter(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="s1", name="S1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="shorts_9x16", available=True,
        ))
        reg.register(TemplateMetadata(
            template_id="s2", name="S2", format="youtube_short",
            aspect_ratio="9:16", adapter_id="shorts_9x16", available=True,
        ))
        results = reg.filter_by_adapter("shorts_9x16")
        self.assertEqual(len(results), 2)

    def test_select_by_format_and_aspect(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="t1", name="T1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="s", available=True,
        ))
        result = reg.select(platform="youtube_short", aspect_ratio="9:16")
        self.assertEqual(result.template_id, "t1")

    def test_select_unavailable_raises(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="t1", name="T1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="s", available=False,
        ))
        with self.assertRaises(TemplateUnavailableError):
            reg.select(platform="youtube_short", aspect_ratio="9:16")

    def test_select_incompatible_raises(self):
        reg = TemplateRegistry()
        with self.assertRaises(TemplateIncompatibleError):
            reg.select(platform="youtube_short", aspect_ratio="16:9")

    def test_validate_compatibility(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="t1", name="T1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="s", available=True,
            supported_content_types=("youtube_short",),
            supported_dynamic_fields=("title", "text"),
        ))
        result = reg.validate_compatibility("t1", "youtube_short", "9:16")
        self.assertTrue(result["format_match"])
        self.assertTrue(result["aspect_match"])
        self.assertTrue(result["available"])
        self.assertTrue(result["compatible"])

    def test_get_template_ids(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="t1", name="T1", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=True,
        ))
        reg.register(TemplateMetadata(
            template_id="t2", name="T2", format="youtube_short",
            aspect_ratio="9:16", adapter_id="s", available=True,
        ))
        ids = reg.get_template_ids()
        self.assertIn("t1", ids)
        self.assertIn("t2", ids)


class TestTemplateMetadata(unittest.TestCase):
    def test_is_compatible_format(self):
        meta = TemplateMetadata(
            template_id="t1", name="T1", format="youtube_short",
            aspect_ratio="9:16", supported_content_types=("youtube_short", "social_post"),
        )
        self.assertTrue(meta.is_compatible_format("youtube_short"))
        self.assertTrue(meta.is_compatible_format("social_post"))
        self.assertFalse(meta.is_compatible_format("youtube_long"))

    def test_is_compatible_format_empty_types(self):
        meta = TemplateMetadata(
            template_id="t1", name="T1", format="youtube_short",
            aspect_ratio="9:16",
        )
        self.assertTrue(meta.is_compatible_format("anything"))

    def test_is_compatible_aspect(self):
        meta = TemplateMetadata(
            template_id="t1", name="T1", format="youtube_short",
            aspect_ratio="9:16",
        )
        self.assertTrue(meta.is_compatible_aspect("9:16"))
        self.assertFalse(meta.is_compatible_aspect("16:9"))
