"""Tests for real template integration - template adapters."""
import unittest
import os
import re
from templates.adapters.base import TemplateAdapter
from templates.adapters.registry import TemplateAdapterRegistry, ADAPTER_CONFIGS
from templates.loader import TemplateLoader
from templates.metadata import TemplateMetadata
from templates.registry import TemplateRegistry
from templates.populated import TemplatePopulator
from templates.exceptions import TemplateNotFoundError, TemplateUnavailableError


ADAPTERS = TemplateAdapterRegistry()
LOADER = TemplateLoader(templates_dir="templates")
REGISTRY = TemplateRegistry()

FUNCTIONAL_TEMPLATES = [
    "01_Focus_Habits_Shorts_9x16",
    "02_Geeta_Gyaan_9x16",
    "03_General_Quiz_9x16",
    "04_Science_Quiz_9x16",
    "05_Science_Storytelling_9x16",
    "06_Indian_Traditional_Story_9x16",
    "07_Indian_Heritage_Story_16x9",
    "08_Crime_Files_16x9",
    "14_AI_Neural_Intelligence_16x9",
    "15_AI_Digital_Future_16x9",
]

STUB_TEMPLATES = [
    "09_Finance_Base_16x9",
    "10_Finance_Wall_Street_Terminal_16x9",
    "11_Finance_Luxury_Wealth_16x9",
    "12_Finance_Economic_Documentary_16x9",
    "13_Finance_Future_FinTech_16x9",
    "16_Newsroom_16x9",
    "17_Sports_Arena_16x9",
    "18_Entertainment_Red_Carpet_16x9",
    "19_Movies_Recommendation_16x9",
]

for _tid in FUNCTIONAL_TEMPLATES + STUB_TEMPLATES:
    _available = _tid in ADAPTER_CONFIGS
    REGISTRY.register(TemplateMetadata(
        template_id=_tid,
        name=_tid,
        format="youtube_short" if "9x16" in _tid else "youtube_long",
        aspect_ratio="9:16" if "9x16" in _tid else "16:9",
        adapter_id="shorts_9x16" if "9x16" in _tid else "long_16x9",
        available=_available,
    ))

POPULATOR = TemplatePopulator(adapter_registry=ADAPTERS)


class TestAdapterConfigs(unittest.TestCase):
    def test_all_functional_have_adapters(self):
        for tid in FUNCTIONAL_TEMPLATES:
            self.assertIn(tid, ADAPTER_CONFIGS, f"Missing config for {tid}")

    def test_adapter_configs_have_required_fields(self):
        for tid, config in ADAPTER_CONFIGS.items():
            self.assertIn("data_var", config, f"{tid} missing data_var")
            self.assertIn("field_map", config, f"{tid} missing field_map")

    def test_adapter_instances(self):
        for tid in FUNCTIONAL_TEMPLATES:
            adapter = ADAPTERS.get_adapter(tid)
            self.assertIsInstance(adapter, TemplateAdapter)

    def test_adapter_data_variable(self):
        for tid in FUNCTIONAL_TEMPLATES:
            adapter = ADAPTERS.get_adapter(tid)
            self.assertTrue(adapter.get_data_variable())

    def test_adapter_theme_vars(self):
        adapter = ADAPTERS.get_adapter("01_Focus_Habits_Shorts_9x16")
        self.assertIn("bg", adapter.get_theme_vars())
        self.assertIn("accent", adapter.get_theme_vars())


class TestRealTemplateLoading(unittest.TestCase):
    def test_load_all_functional(self):
        for tid in FUNCTIONAL_TEMPLATES:
            html, meta = LOADER.load(tid)
            self.assertTrue(len(html) > 0, f"{tid} should have HTML")
            self.assertIn("<html", html.lower(), f"{tid} should have html tag")

    def test_load_all_stubs(self):
        for tid in STUB_TEMPLATES:
            html, meta = LOADER.load(tid)
            self.assertTrue(len(html) > 0, f"{tid} should have HTML")


class TestRealTemplateRegistry(unittest.TestCase):
    def test_register_all_functional(self):
        for tid in FUNCTIONAL_TEMPLATES:
            meta = REGISTRY.lookup(tid)
            self.assertEqual(meta.template_id, tid)

    def test_functional_format_compatibility(self):
        for tid in FUNCTIONAL_TEMPLATES:
            meta = REGISTRY.lookup(tid)
            fmt = meta.format
            result = REGISTRY.validate_compatibility(tid, fmt, meta.aspect_ratio)
            self.assertTrue(result["compatible"])

    def test_stubs_marked_unavailable(self):
        for tid in STUB_TEMPLATES:
            meta = REGISTRY.lookup(tid)
            self.assertFalse(meta.available)

    def test_select_shorts_template(self):
        result = REGISTRY.select(platform="youtube_short", aspect_ratio="9:16")
        self.assertIn(result.template_id, FUNCTIONAL_TEMPLATES)

    def test_select_long_template(self):
        result = REGISTRY.select(platform="youtube_long", aspect_ratio="16:9")
        self.assertIn(result.template_id, FUNCTIONAL_TEMPLATES)

    def test_select_unavailable_raises(self):
        from templates.exceptions import TemplateIncompatibleError
        with self.assertRaises(TemplateIncompatibleError):
            REGISTRY.select(platform="carousel", aspect_ratio="1:1")


class TestAdapterDataGeneration(unittest.TestCase):
    def test_focus_habits_generates_slides_data(self):
        adapter = ADAPTERS.get_adapter("01_Focus_Habits_Shorts_9x16")
        content = {
            "scenes": [
                {"title": "Habit 1", "text": "Text of habit 1"},
                {"title": "Habit 2", "text": "Text of habit 2"},
            ]
        }
        code = adapter.generate_data_code(content)
        self.assertIn("const slidesData", code)
        self.assertIn("Habit 1", code)
        self.assertIn("Habit 2", code)
        self.assertIn("Text of habit 1", code)

    def test_geeta_gyaan_generates_slides_data(self):
        adapter = ADAPTERS.get_adapter("02_Geeta_Gyaan_9x16")
        content = {
            "scenes": [
                {"chapter": "कर्म", "title": "कर्म करते जाओ", "text": "Do your duty.", "image": "krishna.jpg"},
            ]
        }
        code = adapter.generate_data_code(content)
        self.assertIn("const slidesData", code)
        self.assertIn("कर्म", code)
        self.assertIn("कर्म करते जाओ", code)
        self.assertIn("krishna.jpg", code)

    def test_quiz_generates_quiz_data(self):
        adapter = ADAPTERS.get_adapter("03_General_Quiz_9x16")
        content = {
            "scenes": [
                {
                    "category": "SCIENCE",
                    "title": "Which planet is the Red Planet?",
                    "text": "Mars appears reddish...",
                },
            ]
        }
        code = adapter.generate_data_code(content)
        self.assertIn("const quizData", code)
        self.assertIn("SCIENCE", code)
        self.assertIn("Red Planet", code)

    def test_storytelling_generates_story_data(self):
        adapter = ADAPTERS.get_adapter("05_Science_Storytelling_9x16")
        content = {
            "scenes": [
                {"chapter": "SCIENCE", "title": "Story Title", "text": "Story text.", "image": "img.jpg", "textPosition": "left"},
            ]
        }
        code = adapter.generate_data_code(content)
        self.assertIn("const storyData", code)
        self.assertIn("SCIENCE", code)
        self.assertIn("img.jpg", code)
        self.assertIn("left", code)

    def test_crime_generates_crime_data(self):
        adapter = ADAPTERS.get_adapter("08_Crime_Files_16x9")
        content = {
            "scenes": [
                {"chapter": "CASE 1", "title": "Crime Title", "text": "Crime text.", "image": "crime.jpg", "textPosition": "right"},
            ]
        }
        code = adapter.generate_data_code(content)
        self.assertIn("const crimeData", code)
        self.assertIn("CASE 1", code)
        self.assertIn("crime.jpg", code)

    def test_ai_neural_generates_ai_data(self):
        adapter = ADAPTERS.get_adapter("14_AI_Neural_Intelligence_16x9")
        content = {
            "scenes": [
                {
                    "section": "AI SYSTEMS",
                    "title": "AI Title",
                    "narration": "AI narration text.",
                    "image": "ai.jpg",
                    "textPosition": "left",
                    "signal": "PATTERN",
                    "sub": "LEARNING",
                },
            ]
        }
        code = adapter.generate_data_code(content)
        self.assertIn("const aiData", code)
        self.assertIn("AI SYSTEMS", code)
        self.assertIn("PATTERN", code)

    def test_ai_digital_generates_ai_data(self):
        adapter = ADAPTERS.get_adapter("15_AI_Digital_Future_16x9")
        content = {
            "scenes": [
                {
                    "section": "GENERATIVE AI",
                    "title": "AI Title",
                    "narration": "AI narration text.",
                    "image": "ai.jpg",
                    "textPosition": "right",
                    "metric": "GEN-AI",
                    "desc": "MULTIMODAL",
                },
            ]
        }
        code = adapter.generate_data_code(content)
        self.assertIn("const aiData", code)
        self.assertIn("GENERATIVE AI", code)
        self.assertIn("GEN-AI", code)


class TestTemplatePopulation(unittest.TestCase):
    def test_populate_focus_habits(self):
        adapter = ADAPTERS.get_adapter("01_Focus_Habits_Shorts_9x16")
        html, _ = LOADER.load("01_Focus_Habits_Shorts_9x16")
        content = {
            "scenes": [
                {"title": "Test Habit", "text": "Test text for habit."},
            ]
        }
        result = adapter.populate(html, content)
        self.assertIn("Test Habit", result)
        self.assertIn("Test text for habit.", result)
        self.assertIn("const slidesData", result)

    def test_populate_geeta_gyaan(self):
        adapter = ADAPTERS.get_adapter("02_Geeta_Gyaan_9x16")
        html, _ = LOADER.load("02_Geeta_Gyaan_9x16")
        content = {
            "scenes": [
                {"chapter": "धैर्य", "title": "धैर्य", "text": "Test.", "image": "test.jpg"},
            ]
        }
        result = adapter.populate(html, content)
        self.assertIn("धैर्य", result)
        self.assertIn("test.jpg", result)
        self.assertIn("const slidesData", result)

    def test_populate_with_theme(self):
        adapter = ADAPTERS.get_adapter("01_Focus_Habits_Shorts_9x16")
        html, _ = LOADER.load("01_Focus_Habits_Shorts_9x16")
        content = {"scenes": [{"title": "T", "text": "X"}]}
        theme = {"bg": "#ff0000", "accent": "#00ff00"}
        result = adapter.populate(html, content, theme=theme)
        self.assertIn("--bg:#ff0000", result)
        self.assertIn("--accent:#00ff00", result)

    def test_populate_no_theme_preserves_original(self):
        adapter = ADAPTERS.get_adapter("01_Focus_Habits_Shorts_9x16")
        html, _ = LOADER.load("01_Focus_Habits_Shorts_9x16")
        content = {"scenes": [{"title": "T", "text": "X"}]}
        result = adapter.populate(html, content)
        self.assertIn("var(--bg)", result)
        self.assertNotIn("--bg:#ff0000", result)

    def test_populate_crime_files(self):
        adapter = ADAPTERS.get_adapter("08_Crime_Files_16x9")
        html, _ = LOADER.load("08_Crime_Files_16x9")
        content = {
            "scenes": [
                {"chapter": "CASE 1", "title": "Test Crime", "text": "Crime story.", "image": "test.jpg", "textPosition": "left"},
            ]
        }
        result = adapter.populate(html, content)
        self.assertIn("CASE 1", result)
        self.assertIn("Test Crime", result)
        self.assertIn("test.jpg", result)
        self.assertIn("const crimeData", result)

    def test_populate_ai_neural(self):
        adapter = ADAPTERS.get_adapter("14_AI_Neural_Intelligence_16x9")
        html, _ = LOADER.load("14_AI_Neural_Intelligence_16x9")
        content = {
            "scenes": [
                {
                    "section": "AI SYSTEMS",
                    "title": "Test AI",
                    "narration": "Test narration.",
                    "image": "test.jpg",
                    "textPosition": "left",
                    "signal": "PATTERN",
                    "sub": "LEARNING",
                },
            ]
        }
        result = adapter.populate(html, content)
        self.assertIn("AI SYSTEMS", result)
        self.assertIn("Test AI", result)
        self.assertIn("Test narration.", result)
        self.assertIn("test.jpg", result)
        self.assertIn("const aiData", result)


class TestPopulatedOutput(unittest.TestCase):
    def test_populate_and_save_creates_file(self):
        populator = TemplatePopulator(adapter_registry=ADAPTERS)
        template_id = "01_Focus_Habits_Shorts_9x16"
        content = {"scenes": [{"title": "Test", "text": "Hello"}]}
        path = populator.populate_and_save(template_id, content)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            html = f.read()
        self.assertIn("Test", html)

    def test_populated_html_contains_content(self):
        populator = TemplatePopulator(adapter_registry=ADAPTERS)
        template_id = "02_Geeta_Gyaan_9x16"
        content = {"scenes": [{"chapter": "धैर्य", "title": "Test", "text": "Hello", "image": "img.jpg"}]}
        path = populator.populate_and_save(template_id, content)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("धैर्य", html)
        self.assertIn("Test", html)
        self.assertIn("img.jpg", html)

    def test_populated_html_is_readable(self):
        populator = TemplatePopulator(adapter_registry=ADAPTERS)
        for tid in FUNCTIONAL_TEMPLATES:
            content = {"scenes": [{"title": "Test", "text": "Hello"}]}
            path = populator.populate_and_save(tid, content)
            self.assertTrue(os.path.isfile(path))
            with open(path, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("<html", html.lower())
            self.assertGreater(len(html), 100)


class TestOriginalTemplatePreservation(unittest.TestCase):
    def test_templates_unchanged_after_population(self):
        import hashlib
        for tid in FUNCTIONAL_TEMPLATES:
            path = os.path.join("templates", f"{tid}.html")
            with open(path, "rb") as f:
                original_hash = hashlib.md5(f.read()).hexdigest()
            populator = TemplatePopulator(adapter_registry=ADAPTERS)
            populator.populate_and_save(tid, {"scenes": [{"title": "Modified", "text": "Changed"}]})
            with open(path, "rb") as f:
                after_hash = hashlib.md5(f.read()).hexdigest()
            self.assertEqual(original_hash, after_hash, f"{tid} was modified!")


class TestStubTemplatesRemainIncomplete(unittest.TestCase):
    def test_stubs_unavailable(self):
        for tid in STUB_TEMPLATES:
            meta = REGISTRY.lookup(tid)
            self.assertFalse(meta.available)

    def test_stubs_have_no_dynamic_fields(self):
        for tid in STUB_TEMPLATES:
            meta = REGISTRY.lookup(tid)
            self.assertEqual(len(meta.supported_dynamic_fields), 0)

    def test_stubs_have_no_adapter(self):
        for tid in STUB_TEMPLATES:
            self.assertFalse(ADAPTERS.has_adapter(tid))


class TestFormatCompatibility(unittest.TestCase):
    def test_shorts_templates_are_9x16(self):
        shorts_ids = [
            "01_Focus_Habits_Shorts_9x16",
            "02_Geeta_Gyaan_9x16",
            "03_General_Quiz_9x16",
            "04_Science_Quiz_9x16",
            "05_Science_Storytelling_9x16",
            "06_Indian_Traditional_Story_9x16",
        ]
        for tid in shorts_ids:
            meta = REGISTRY.lookup(tid)
            self.assertEqual(meta.aspect_ratio, "9:16", f"{tid} should be 9:16")

    def test_long_templates_are_16x9(self):
        long_ids = [
            "07_Indian_Heritage_Story_16x9",
            "08_Crime_Files_16x9",
            "14_AI_Neural_Intelligence_16x9",
            "15_AI_Digital_Future_16x9",
        ]
        for tid in long_ids:
            meta = REGISTRY.lookup(tid)
            self.assertEqual(meta.aspect_ratio, "16:9", f"{tid} should be 16:9")


class TestPopulatorIntegration(unittest.TestCase):
    def test_populator_loads_real_templates(self):
        populator = TemplatePopulator(adapter_registry=ADAPTERS)
        for tid in FUNCTIONAL_TEMPLATES:
            html = populator.get_original_template(tid)
            self.assertTrue(len(html) > 0)

    def test_populator_populates_all_functional(self):
        populator = TemplatePopulator(adapter_registry=ADAPTERS)
        for tid in FUNCTIONAL_TEMPLATES:
            content = {"scenes": [{"title": "Test", "text": "Content"}]}
            result = populator.populate(tid, content)
            self.assertIn("Test", result)

    def test_populator_placeholder_for_stubs(self):
        populator = TemplatePopulator(adapter_registry=ADAPTERS)
        for tid in STUB_TEMPLATES:
            result = populator.populate(tid, {"scenes": []})
            self.assertIn("unavailable", result.lower())
