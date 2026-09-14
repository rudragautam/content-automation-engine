"""Tests for template loader."""
import unittest
import tempfile
import os
from templates.loader import TemplateLoader
from templates.exceptions import TemplateNotFoundError, TemplateUnavailableError


class TestTemplateLoader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.loader = TemplateLoader(templates_dir=self.temp_dir)

    def test_load_existing_template(self):
        with open(os.path.join(self.temp_dir, "test.html"), "w") as f:
            f.write("<html><body>Test</body></html>")
        html, metadata = self.loader.load("test")
        self.assertIn("Test", html)
        self.assertTrue(metadata.available)
        self.assertEqual(metadata.source_path, os.path.join(self.temp_dir, "test.html"))

    def test_load_missing_raises(self):
        with self.assertRaises(TemplateUnavailableError):
            self.loader.load("nonexistent")

    def test_exists_returns_true(self):
        with open(os.path.join(self.temp_dir, "exists.html"), "w") as f:
            f.write("<html></html>")
        self.assertTrue(self.loader.exists("exists"))

    def test_exists_returns_false(self):
        self.assertFalse(self.loader.exists("does_not_exist"))

    def test_validate_returns_true(self):
        with open(os.path.join(self.temp_dir, "valid.html"), "w") as f:
            f.write("<html></html>")
        self.assertTrue(self.loader.validate("valid"))

    def test_validate_returns_false(self):
        self.assertFalse(self.loader.validate("invalid"))

    def test_empty_file_raises(self):
        with open(os.path.join(self.temp_dir, "empty.html"), "w") as f:
            f.write("")
        with self.assertRaises(TemplateUnavailableError):
            self.loader.load("empty")
