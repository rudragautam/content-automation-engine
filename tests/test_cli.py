"""Tests for CLI argument parsing."""
import unittest
import sys
import io

from engine import parse_args, build_config
from core.run_config import RunConfig
from core.content_mode import ContentMode


class TestCLIParsing(unittest.TestCase):
    def test_default_args(self):
        args = parse_args([])
        self.assertEqual(args.mode, "custom")
        self.assertEqual(args.topic, "")
        self.assertEqual(args.template, "")
        self.assertEqual(args.platform, "youtube_short")

    def test_custom_mode_with_topic(self):
        args = parse_args(["--mode", "custom", "--topic", "My Topic"])
        self.assertEqual(args.mode, "custom")
        self.assertEqual(args.topic, "My Topic")

    def test_template_argument(self):
        args = parse_args(["--template", "02_Geeta_Gyaan_9x16.html"])
        self.assertEqual(args.template, "02_Geeta_Gyaan_9x16.html")

    def test_storyline_args(self):
        args = parse_args(["--storyline", "Point 1", "Point 2"])
        self.assertEqual(args.storyline, ["Point 1", "Point 2"])

    def test_key_points_args(self):
        args = parse_args(["--key-points", "KP1", "KP2"])
        self.assertEqual(args.key_points, ["KP1", "KP2"])

    def test_asset_args(self):
        args = parse_args(["--asset", "bg=/img.png", "--asset", "logo=/logo.png"])
        self.assertEqual(args.asset, ["bg=/img.png", "logo=/logo.png"])

    def test_theme_args(self):
        args = parse_args(["--theme", "bg=#ff0000", "--theme", "accent=#00ff00"])
        self.assertEqual(args.theme, ["bg=#ff0000", "accent=#00ff00"])

    def test_output_dir(self):
        args = parse_args(["--output", "my/output"])
        self.assertEqual(args.output, "my/output")

    def test_verbose(self):
        args = parse_args(["-v"])
        self.assertTrue(args.verbose)


class TestCLIConfigBuild(unittest.TestCase):
    def test_build_config_basic(self):
        args = parse_args(["--mode", "custom", "--topic", "Test"])
        config = build_config(args)
        self.assertEqual(config.mode, ContentMode.CUSTOM)
        self.assertEqual(config.topic, "Test")

    def test_build_config_with_template(self):
        args = parse_args(["--template", "02_Geeta_Gyaan_9x16.html"])
        config = build_config(args)
        self.assertEqual(config.template_id, "02_Geeta_Gyaan_9x16")
        self.assertEqual(config.template_filename, "02_Geeta_Gyaan_9x16.html")

    def test_build_config_with_assets(self):
        args = parse_args(["--asset", "bg=/img.png"])
        config = build_config(args)
        self.assertEqual(config.assets["bg"], "/img.png")

    def test_build_config_with_theme(self):
        args = parse_args(["--theme", "bg=#ff0000"])
        config = build_config(args)
        self.assertEqual(config.theme["bg"], "#ff0000")

    def test_build_config_storyline(self):
        args = parse_args(["--storyline", "A", "B"])
        config = build_config(args)
        self.assertEqual(config.storyline, ("A", "B"))
