"""Tests for platform specifications."""
import unittest
from core.specs import get_spec, SPECS, PlatformSpec, YouTubeShortSpec, YouTubeLongSpec, SocialPostSpec, CarouselSpec


class TestYouTubeShortSpec(unittest.TestCase):
    def test_spec_values(self):
        spec = SPECS["youtube_short"]
        self.assertEqual(spec.platform, "youtube_short")
        self.assertEqual(spec.format, "short_video")
        self.assertEqual(spec.max_length, 60)
        self.assertIn("hook", spec.structure)


class TestYouTubeLongSpec(unittest.TestCase):
    def test_spec_values(self):
        spec = SPECS["youtube_long"]
        self.assertEqual(spec.platform, "youtube_long")
        self.assertEqual(spec.format, "long_video")
        self.assertIsNone(spec.max_length)
        self.assertIn("intro", spec.structure)


class TestSocialPostSpec(unittest.TestCase):
    def test_spec_values(self):
        spec = SPECS["social_post"]
        self.assertEqual(spec.platform, "social_post")
        self.assertEqual(spec.format, "post")
        self.assertEqual(spec.max_length, 280)


class TestCarouselSpec(unittest.TestCase):
    def test_spec_values(self):
        spec = SPECS["carousel"]
        self.assertEqual(spec.platform, "carousel")
        self.assertEqual(spec.format, "carousel")
        self.assertEqual(spec.slide_count, 5)


class TestGetSpec(unittest.TestCase):
    def test_youtube_short(self):
        spec = get_spec("youtube_short")
        self.assertEqual(spec.platform, "youtube_short")

    def test_youtube_long(self):
        spec = get_spec("youtube_long")
        self.assertEqual(spec.platform, "youtube_long")

    def test_social_post(self):
        spec = get_spec("social_post")
        self.assertEqual(spec.platform, "social_post")

    def test_carousel(self):
        spec = get_spec("carousel")
        self.assertEqual(spec.platform, "carousel")

    def test_youtube_short_with_format(self):
        spec = get_spec("youtube_short", "short_video")
        self.assertEqual(spec.platform, "youtube_short")

    def test_default_fallback(self):
        spec = get_spec("unknown_platform")
        self.assertIsNotNone(spec)


class TestSpecsContainAllPlatforms(unittest.TestCase):
    def test_all_platforms_present(self):
        expected = {"youtube_short", "youtube_long", "social_post", "carousel"}
        self.assertEqual(set(SPECS.keys()), expected)
