"""Tests for template populator."""
import unittest
from templates.populator import TemplatePopulator


class TestTemplatePopulator(unittest.TestCase):
    def setUp(self):
        self.populator = TemplatePopulator()

    def test_populate_data_markers_double_brace(self):
        html = '<h1>{{title}}</h1>'
        data = {"title": "My Title"}
        result = self.populator.populate(html, data)
        self.assertIn("My Title", result)

    def test_populate_data_markers_single_brace(self):
        html = '<h1>{{title}}</h1>'
        data = {"title": "My Title"}
        result = self.populator.populate(html, data)
        self.assertIn("My Title", result)

    def test_populate_preserves_html_structure(self):
        html = '<html><head><title>{{title}}</title></head><body>{{body}}</body></html>'
        data = {"title": "Test", "body": "Content"}
        result = self.populator.populate(html, data)
        self.assertIn("<html>", result)
        self.assertIn("</html>", result)
        self.assertIn("Test", result)
        self.assertIn("Content", result)

    def test_populate_missing_key_keeps_marker(self):
        html = '<h1>{{missing}}</h1>'
        data = {"title": "Test"}
        result = self.populator.populate(html, data)
        self.assertIn("{{missing}}", result)

    def test_populate_assets(self):
        html = '<img src="{{asset:logo}}">'
        assets = {"logo": "/images/logo.png"}
        result = self.populator.populate(html, {}, assets=assets)
        self.assertIn("/images/logo.png", result)

    def test_populate_theme(self):
        html = '<div style="color: {{theme:accent}}">'
        theme = {"accent": "red"}
        result = self.populator.populate(html, {}, theme=theme)
        self.assertIn("red", result)

    def test_populate_no_data_preserves_html(self):
        html = '<html><body>Static</body></html>'
        result = self.populator.populate(html, {})
        self.assertEqual(result, html)

    def test_populate_multiple_markers(self):
        html = '{{title}} - {{body}}'
        data = {"title": "Hello", "body": "World"}
        result = self.populator.populate(html, data)
        self.assertEqual(result, "Hello - World")

    def test_populate_complex_html(self):
        html = """<!DOCTYPE html>
<html>
<head><title>{{title}}</title></head>
<body>
<h1>{{title}}</h1>
<p>{{content}}</p>
<div style="color: {{theme:accent}}">{{content}}</div>
</body>
</html>"""
        data = {"title": "Test", "content": "Body text"}
        theme = {"accent": "blue"}
        result = self.populator.populate(html, data, theme=theme)
        self.assertIn("Test", result)
        self.assertIn("Body text", result)
        self.assertIn("blue", result)
