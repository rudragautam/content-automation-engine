"""Tests for run configuration."""
import unittest
from core.run_config import RunConfig
from core.content_mode import ContentMode


class TestRunConfigDefaults(unittest.TestCase):
    def test_default_mode(self):
        config = RunConfig()
        self.assertEqual(config.mode, ContentMode.AUTO)

    def test_default_topic_empty(self):
        config = RunConfig()
        self.assertEqual(config.topic, "")

    def test_default_output_dir(self):
        config = RunConfig()
        self.assertEqual(config.output_dir, "output/runs")

    def test_default_template_none(self):
        config = RunConfig()
        self.assertIsNone(config.template_id)


class TestRunConfigValidation(unittest.TestCase):
    def test_valid_custom(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test Topic",
            platform="youtube_short",
            content_format="short_video",
            aspect_ratio="9:16",
        )
        errors = config.validate()
        self.assertEqual(errors, [])

    def test_invalid_mode(self):
        config = RunConfig(mode="invalid", topic="Test")
        errors = config.validate()
        self.assertTrue(any("mode" in e.lower() for e in errors))

    def test_unsupported_aspect(self):
        config = RunConfig(aspect_ratio="4:3")
        errors = config.validate()
        self.assertTrue(any("aspect" in e.lower() for e in errors))

    def test_custom_requires_content(self):
        config = RunConfig(mode=ContentMode.CUSTOM)
        errors = config.validate()
        self.assertTrue(any("requires" in e.lower() for e in errors))

    def test_custom_with_storyline_valid(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            storyline=("Point 1", "Point 2"),
        )
        errors = config.validate()
        self.assertEqual(errors, [])

    def test_custom_with_key_points_valid(self):
        config = RunConfig(
            mode=ContentMode.CUSTOM,
            topic="Test",
            key_points=("Point 1",),
        )
        errors = config.validate()
        self.assertEqual(errors, [])


class TestRunConfigGetAspect(unittest.TestCase):
    def test_explicit_aspect(self):
        config = RunConfig(aspect_ratio="16:9")
        self.assertEqual(config.get_aspect_from_platform(), "16:9")

    def test_default_short(self):
        config = RunConfig(platform="youtube_short")
        self.assertEqual(config.get_aspect_from_platform(), "9:16")

    def test_default_long(self):
        config = RunConfig(platform="youtube_long")
        self.assertEqual(config.get_aspect_from_platform(), "16:9")


class TestRunConfigAssets(unittest.TestCase):
    def test_empty_assets(self):
        config = RunConfig()
        self.assertEqual(config.assets, {})

    def test_with_assets(self):
        config = RunConfig(assets={"bg": "/img.png"})
        self.assertEqual(config.assets["bg"], "/img.png")
