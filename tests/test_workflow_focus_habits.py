"""Tests for the 01 Focus Habits workflow and its timing rules."""
import json
import os
import re
import shutil
import tempfile
import unittest

from workflows.focus_habits import FocusHabitsWorkflow
from workflows.registry import get_workflow, has_workflow
from workflows.timing import clamp_seconds, reading_seconds, typing_seconds, word_count

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "01_focus_habits.json")


def load_example():
    with open(EXAMPLE, "r", encoding="utf-8") as f:
        return json.load(f)


class TestTimingRules(unittest.TestCase):
    def test_word_count_ignores_emoji_and_punctuation(self):
        self.assertEqual(word_count("📱 PHONE CHECKING", "a, b."), 4)

    def test_reading_seconds(self):
        self.assertAlmostEqual(reading_seconds("one two three"), 1.0)

    def test_typing_seconds(self):
        self.assertAlmostEqual(typing_seconds("x" * 100, 28), 2.8)

    def test_clamp_seconds(self):
        self.assertEqual(clamp_seconds(1.234, 3, 10), 3)
        self.assertEqual(clamp_seconds(12, 3, 10), 10)
        self.assertEqual(clamp_seconds(6.66, 3, 10), 6.7)


class TestFocusHabitsPlan(unittest.TestCase):
    def setUp(self):
        self.workflow = FocusHabitsWorkflow()

    def test_plan_has_intro_then_habits(self):
        plan = self.workflow.plan(load_example())
        self.assertEqual([s.kind for s in plan.slides], ["intro"] + ["habit"] * 5)

    def test_longer_text_gets_longer_duration(self):
        plan = self.workflow.plan({
            "intro": {"title": "T"},
            "slides": [
                {"title": "Short", "text": "Sleep matters."},
                {"title": "Long", "text": " ".join(["focus"] * 20)},
            ],
        })
        self.assertLess(plan.slides[1].duration, plan.slides[2].duration)

    def test_durations_stay_in_range(self):
        plan = self.workflow.plan({
            "intro": {"title": "T"},
            "slides": [{"title": "A", "text": "B"}, {"title": "A", "text": " ".join(["word"] * 200)}],
        })
        self.assertEqual(plan.slides[0].duration, 2.5)
        self.assertEqual(plan.slides[1].duration, 2.0)
        self.assertEqual(plan.slides[2].duration, 10.0)

    def test_habit_slide_changes_right_after_typing_finishes(self):
        text = "x" * 100  # typed in 2.8s
        plan = self.workflow.plan({"intro": {"title": "T"}, "slides": [{"title": "A", "text": text}]})
        self.assertEqual(plan.slides[1].duration, 3.6)

    def test_manual_override(self):
        plan = self.workflow.plan({"intro": {"title": "T"}, "slides": [{"title": "A", "text": "B", "duration": 7}]})
        self.assertEqual(plan.slides[1].duration, 7.0)
        self.assertEqual(plan.slides[1].reason, "manual override")

    def test_every_slide_explains_its_duration(self):
        plan = self.workflow.plan(load_example())
        self.assertTrue(all(s.reason for s in plan.slides))

    def test_missing_fields_rejected(self):
        with self.assertRaises(ValueError):
            self.workflow.plan({"intro": {}, "slides": [{"title": "A", "text": "B"}]})
        with self.assertRaises(ValueError):
            self.workflow.plan({"intro": {"title": "T"}, "slides": []})
        with self.assertRaises(ValueError):
            self.workflow.plan({"intro": {"title": "T"}, "slides": [{"title": "A"}]})

    def test_too_long_for_a_short(self):
        slides = [{"title": "A", "text": "B", "duration": 10} for _ in range(7)]
        plan = self.workflow.plan({"intro": {"title": "T"}, "slides": slides})
        self.assertTrue(any("limit" in e for e in self.workflow.validate(plan)))


class TestFocusHabitsPopulate(unittest.TestCase):
    def test_populate_writes_intro_and_slide_durations(self):
        workflow = FocusHabitsWorkflow()
        plan = workflow.plan(load_example())
        html, _ = workflow.loader.load(workflow.template_id)
        populated = workflow.populate(html, plan)

        intro = json.loads(re.search(r"const introData=(\{.*?\});", populated).group(1))
        slides = json.loads(re.search(r"const slidesData=(\[.*?\]);", populated, re.DOTALL).group(1))
        self.assertEqual(intro["title"], "5 Daily Habits That Ruin Your Focus")
        self.assertEqual(intro["duration"], plan.slides[0].duration)
        self.assertEqual([s["duration"] for s in slides], [s.duration for s in plan.slides[1:]])

    def test_populate_escapes_script_close(self):
        workflow = FocusHabitsWorkflow()
        plan = workflow.plan({"intro": {"title": "</script>"}, "slides": [{"title": "A", "text": "B"}]})
        html, _ = workflow.loader.load(workflow.template_id)
        self.assertNotIn("</script>\"", workflow.populate(html, plan))


class TestFocusHabitsRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_without_render_writes_artifacts(self):
        result = FocusHabitsWorkflow().run(load_example(), output_dir=self.tmp, render=False)
        self.assertTrue(result["success"])
        self.assertTrue(os.path.isfile(result["populated_html"]))
        with open(result["timeline"], encoding="utf-8") as f:
            timeline = json.load(f)
        self.assertEqual(len(timeline["slides"]), 6)
        self.assertEqual(timeline["total_seconds"], result["total_seconds"])

    def test_run_reports_invalid_content(self):
        result = FocusHabitsWorkflow().run({"slides": []}, output_dir=self.tmp, render=False)
        self.assertFalse(result["success"])


class TestWorkflowRegistry(unittest.TestCase):
    def test_lookup(self):
        self.assertTrue(has_workflow("01_Focus_Habits_Shorts_9x16"))
        self.assertIsInstance(get_workflow("01_Focus_Habits_Shorts_9x16"), FocusHabitsWorkflow)
        self.assertFalse(has_workflow("02_Geeta_Gyaan_9x16"))


if __name__ == "__main__":
    unittest.main()
