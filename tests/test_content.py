"""Tests for content format models."""
import unittest
from core.content import (
    ShortsContent,
    LongFormContent,
    SocialContent,
    CarouselContent,
    Scene,
    Chapter,
    Section,
    Slide,
)


class TestShortsContent(unittest.TestCase):
    def test_create_shorts(self):
        scene = Scene(scene_id="s1", title="Hook", text="Intro text", narration="Narrated")
        content = ShortsContent(
            content_id="sh-1",
            title="Test Story",
            hook="Amazing fact",
            intro="Opening",
            scenes=(scene,),
            cta="Subscribe",
        )
        self.assertEqual(content.content_id, "sh-1")
        self.assertEqual(content.title, "Test Story")
        self.assertEqual(content.hook, "Amazing fact")
        self.assertEqual(len(content.scenes), 1)
        self.assertEqual(content.scenes[0].title, "Hook")
        self.assertEqual(content.scenes[0].narration, "Narrated")
        self.assertEqual(content.cta, "Subscribe")

    def test_shorts_with_provenance(self):
        content = ShortsContent(
            content_id="sh-1",
            title="Test",
            hook="Hook",
            scenes=(),
            source_references=("https://source.com",),
            factual_claims=("Claim 1",),
        )
        self.assertEqual(content.source_references, ("https://source.com",))

    def test_shorts_immutable(self):
        content = ShortsContent(content_id="c1", title="T", hook="H", scenes=())
        with self.assertRaises(AttributeError):
            content.title = "modified"


class TestLongFormContent(unittest.TestCase):
    def test_create_long_form(self):
        chapter = Chapter(
            chapter_id="ch1",
            title="Chapter 1",
            sections=(Section(section_id="sec1", title="Section 1", text="Body text", narration="Narrated"),),
            narration="Chapter narration",
        )
        content = LongFormContent(
            content_id="lf-1",
            title="Deep Dive",
            intro="Opening",
            chapters=(chapter,),
            cta="Learn more",
        )
        self.assertEqual(content.content_id, "lf-1")
        self.assertEqual(len(content.chapters), 1)
        self.assertEqual(content.chapters[0].title, "Chapter 1")
        self.assertEqual(content.chapters[0].sections[0].text, "Body text")


class TestCarouselContent(unittest.TestCase):
    def test_create_carousel(self):
        slide1 = Slide(slide_id="s1", title="Title 1", body="Body 1")
        slide2 = Slide(slide_id="s2", title="Title 2", body="Body 2", asset="img1")
        content = CarouselContent(
            content_id="cr-1",
            title="My Carousel",
            cover=Slide(slide_id="cover", title="Cover", body="Cover body"),
            slides=(slide1, slide2),
            cta="Swipe next",
        )
        self.assertEqual(content.content_id, "cr-1")
        self.assertEqual(len(content.slides), 2)
        self.assertEqual(content.slides[1].asset, "img1")
        self.assertEqual(content.cover.title, "Cover")


class TestSocialContent(unittest.TestCase):
    def test_create_social(self):
        content = SocialContent(
            content_id="soc-1",
            hook="Catchy hook",
            body="Post body text",
            cta="Link in bio",
            metadata={"platform": "twitter"},
            template_reference="template-001",
        )
        self.assertEqual(content.hook, "Catchy hook")
        self.assertEqual(content.body, "Post body text")
        self.assertEqual(content.metadata["platform"], "twitter")
        self.assertEqual(content.template_reference, "template-001")


class TestSceneStructure(unittest.TestCase):
    def test_scene_with_duration(self):
        scene = Scene(
            scene_id="s1",
            title="Quick Intro",
            text="Welcome",
            narration="Hi there",
            on_screen_text="ON SCREEN",
            duration_ms=5000,
        )
        self.assertEqual(scene.duration_ms, 5000)
        self.assertEqual(scene.on_screen_text, "ON SCREEN")


class TestSlideStructure(unittest.TestCase):
    def test_slide_optional_asset(self):
        slide_with = Slide(slide_id="s1", title="T", body="B", asset="logo.png")
        slide_without = Slide(slide_id="s2", title="T", body="B")
        self.assertEqual(slide_with.asset, "logo.png")
        self.assertIsNone(slide_without.asset)


class TestChapterSectionStructure(unittest.TestCase):
    def test_chapter_with_sections(self):
        section = Section(
            section_id="sec1",
            title="Overview",
            text="Content",
            narration="Narrated",
            scenes=(Scene(scene_id="sc1", title="Scene 1", text="Text"),),
        )
        chapter = Chapter(
            chapter_id="ch1",
            title="Chapter 1",
            sections=(section,),
        )
        self.assertEqual(len(chapter.sections), 1)
        self.assertEqual(chapter.sections[0].scenes[0].title, "Scene 1")
