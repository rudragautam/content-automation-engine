"""Tests for template adapter selection by format."""
import unittest
from templates.registry import TemplateRegistry
from templates.metadata import TemplateMetadata


class TestAdapterSelection(unittest.TestCase):
    def test_select_by_adapter_id(self):
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="t1", name="T1", format="youtube_short",
            aspect_ratio="9:16", adapter_id="shorts_9x16", available=True,
        ))
        results = reg.filter_by_adapter("shorts_9x16")
        self.assertEqual(len(results), 1)


class TestIncompleteTemplateHandling(unittest.TestCase):
    def test_template_without_source(self):
        from templates.registry import TemplateRegistry
        from templates.exceptions import TemplateUnavailableError
        reg = TemplateRegistry()
        reg.register(TemplateMetadata(
            template_id="incomplete", name="Incomplete", format="youtube_long",
            aspect_ratio="16:9", adapter_id="l", available=False, source_path=None,
        ))
        with self.assertRaises(TemplateUnavailableError):
            reg.select(platform="youtube_long", aspect_ratio="16:9")

    def test_template_inventory_marked_unavailable(self):
        from templates.inventory import TEMPLATE_INVENTORY
        for item in TEMPLATE_INVENTORY:
            self.assertFalse(item.get("available", True), f"{item['template_id']} should be unavailable")
            self.assertIsNone(item.get("source_path"), f"{item['template_id']} should not have source path")
