"""Tests for asset system."""
import unittest
import tempfile
import os
from media.asset import Asset, ValidationResult
from media.validation import AssetValidator


class TestAssetMetadata(unittest.TestCase):
    def test_create_asset(self):
        asset = Asset(
            asset_id="a1",
            path="assets/image.png",
            type="image",
            source="user_upload",
            attribution="User",
            description="Test image",
            dimensions="1920x1080",
            assigned_to="scene",
            role="background",
        )
        self.assertEqual(asset.asset_id, "a1")
        self.assertEqual(asset.path, "assets/image.png")
        self.assertEqual(asset.type, "image")
        self.assertEqual(asset.source, "user_upload")
        self.assertEqual(asset.attribution, "User")
        self.assertEqual(asset.role, "background")

    def test_asset_optional_fields(self):
        asset = Asset(asset_id="a1", path="img.png", type="image")
        self.assertIsNone(asset.source)
        self.assertIsNone(asset.attribution)
        self.assertIsNone(asset.assigned_to)
        self.assertIsNone(asset.role)

    def test_is_image(self):
        image = Asset(asset_id="a1", path="img.png", type="image")
        screenshot = Asset(asset_id="a2", path="ss.png", type="screenshot")
        logo = Asset(asset_id="a3", path="logo.png", type="logo")
        chart = Asset(asset_id="a4", path="chart.png", type="chart")
        ref = Asset(asset_id="a5", path="ref.png", type="reference_media")
        for a in (image, screenshot, logo, chart, ref):
            self.assertTrue(a.is_image())
        video = Asset(asset_id="a6", path="vid.mp4", type="video")
        self.assertFalse(video.is_image())


class TestAssetValidation(unittest.TestCase):
    def setUp(self):
        self.validator = AssetValidator()

    def test_valid_asset(self):
        asset = Asset(asset_id="a1", path="assets/img.png", type="image")
        result = self.validator.validate(asset)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    def test_missing_asset_id(self):
        asset = Asset(asset_id="", path="img.png", type="image")
        result = self.validator.validate(asset)
        self.assertFalse(result.valid)
        self.assertTrue(any("asset_id" in e for e in result.errors))

    def test_missing_path(self):
        asset = Asset(asset_id="a1", path="", type="image")
        result = self.validator.validate(asset)
        self.assertFalse(result.valid)
        self.assertTrue(any("path" in e for e in result.errors))

    def test_unsupported_type(self):
        asset = Asset(asset_id="a1", path="img.png", type="unsupported")
        result = self.validator.validate(asset)
        self.assertFalse(result.valid)
        self.assertTrue(any("unsupported" in e for e in result.errors))

    def test_unsafe_path(self):
        asset = Asset(asset_id="a1", path="http://evil.com/img.png", type="image")
        result = self.validator.validate(asset)
        self.assertFalse(result.valid)
        self.assertTrue(any("unsafe" in e for e in result.errors))

    def test_https_path_is_unsafe(self):
        asset = Asset(asset_id="a1", path="https://example.com/img.png", type="image")
        result = self.validator.validate(asset)
        self.assertFalse(result.valid)

    def test_http_path_is_unsafe(self):
        asset = Asset(asset_id="a1", path="http://example.com/img.png", type="image")
        result = self.validator.validate(asset)
        self.assertFalse(result.valid)

    def test_valid_paths(self):
        for path in ("/abs/path/img.png", "./rel/path/img.png", "../up/img.png", "assets/img.png", "./img.png"):
            asset = Asset(asset_id="a1", path=path, type="image")
            result = self.validator.validate(asset)
            self.assertTrue(result.valid, f"Path {path} should be valid")

    def test_valid_assignments(self):
        for assignment in ("scene", "scenes", "slide", "slides", "section", "sections", "cover", "slot", "slots"):
            asset = Asset(asset_id="a1", path="./img.png", type="image", assigned_to=assignment)
            result = self.validator.validate(asset)
            self.assertTrue(result.valid, f"Assignment {assignment} should be valid")

    def test_missing_file_warning(self):
        asset = Asset(asset_id="a1", path="/nonexistent/file.png", type="image")
        result = self.validator.validate(asset)
        self.assertTrue(result.valid, "Missing file should be warning only")
        self.assertTrue(len(result.warnings) > 0, "Should have warnings")


class TestAssetInTempDir(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.validator = AssetValidator(base_dir=self.temp_dir)
        with open(os.path.join(self.temp_dir, "real.png"), "w") as f:
            f.write("fake image data")

    def test_file_exists_passes(self):
        asset = Asset(asset_id="a1", path="./real.png", type="image")
        result = self.validator.validate(asset)
        self.assertTrue(result.valid)
        self.assertEqual(len(result.warnings), 0)
