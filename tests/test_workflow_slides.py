"""Tests for the generic slide workflows (templates 02-08, 14, 15)."""
import json
import re
import unittest

from content_templates import NICHES, get_spec
from content_templates.excel import read_rows
from workflows.registry import WORKFLOWS, get_workflow, has_workflow
from workflows.slides import (
    AIDigitalFutureWorkflow,
    GeetaGyaanWorkflow,
    GeneralQuizWorkflow,
    QuizWorkflow,
    ScienceStoryWorkflow,
    SlideWorkflow,
    TypedWorkflow,
)
from workflows.timing import word_count


def example_content(niche):
    spec = get_spec(niche)
    result = read_rows([spec.example], spec, first_row=1)
    assert result.ok, result.errors
    return result.videos[0]["content"]


def populated_data(workflow, plan):
    html, _ = workflow.loader.load(workflow.template_id)
    populated = workflow.populate(html, plan)
    intro = json.loads(re.search(r"const introData=(\{.*?\});", populated, re.DOTALL).group(1))
    slides = json.loads(re.search(rf"const {workflow.data_var}=(\[.*?\]);", populated, re.DOTALL).group(1))
    return populated, intro, slides


class TestEveryNicheRenders(unittest.TestCase):
    def test_every_niche_has_a_workflow_for_its_template(self):
        for niche, spec in NICHES.items():
            with self.subTest(niche=niche):
                self.assertTrue(has_workflow(spec.template_id))
                self.assertEqual(get_workflow(spec.template_id).aspect_ratio, spec.aspect_ratio)

    def test_every_example_plans_and_populates(self):
        for niche, spec in NICHES.items():
            with self.subTest(niche=niche):
                workflow = get_workflow(spec.template_id)
                plan = workflow.plan(example_content(niche))
                self.assertEqual(workflow.validate(plan), [])
                self.assertTrue(all(s.reason for s in plan.slides))
                populated, intro, slides = populated_data(workflow, plan) if workflow.template_id != "01_Focus_Habits_Shorts_9x16" else (None, None, None)
                if populated:
                    self.assertEqual(intro["duration"], plan.slides[0].duration)
                    self.assertEqual(len(slides), len([s for s in plan.slides if s.kind == workflow.slide_kind]))

    def test_registry_lists_all_ten(self):
        self.assertEqual(len(WORKFLOWS), 10)


class TestStoryTiming(unittest.TestCase):
    def test_hindi_words_are_counted_whole(self):
        self.assertEqual(word_count("कर्म करते जाओ"), 3)

    def test_longer_scene_lasts_longer_and_stays_in_range(self):
        wf = ScienceStoryWorkflow()
        plan = wf.plan({"intro": {"title": "T"}, "slides": [
            {"chapter": "A", "title": "Short", "text": "One idea."},
            {"chapter": "B", "title": "Long", "text": " ".join(["word"] * 80)},
        ]})
        self.assertLess(plan.slides[1].duration, plan.slides[2].duration)
        self.assertEqual(plan.slides[2].duration, wf.slide_range[1])
        self.assertIn("limited", plan.slides[2].reason)

    def test_geeta_scene_reads_hindi_text(self):
        plan = GeetaGyaanWorkflow().plan(example_content("geeta_gyaan"))
        self.assertEqual([s.kind for s in plan.slides], ["intro"] + ["lesson"] * 4)
        self.assertGreater(plan.slides[1].duration, 5)

    def test_manual_override_and_missing_fields(self):
        wf = ScienceStoryWorkflow()
        plan = wf.plan({"intro": {"title": "T", "duration": 99}, "slides": [{"chapter": "A", "title": "B", "text": "C", "duration": 7}]})
        self.assertEqual((plan.slides[0].duration, plan.slides[1].duration), (6.0, 7.0))
        self.assertNotIn("duration", plan.slides[1].data)
        with self.assertRaises(ValueError):
            wf.plan({"intro": {}, "slides": [{"chapter": "A", "title": "B", "text": "C"}]})
        with self.assertRaises(ValueError):
            wf.plan({"intro": {"title": "T"}, "slides": [{"chapter": "A", "title": "B"}]})

    def test_shorts_limit_is_three_minutes(self):
        wf = ScienceStoryWorkflow()
        slides = [{"chapter": "A", "title": "B", "text": "C", "duration": 12} for _ in range(6)]
        self.assertEqual(wf.validate(wf.plan({"intro": {"title": "T"}, "slides": slides})), [])
        self.assertEqual(wf.max_total_seconds, 180.0)
        self.assertEqual(get_workflow("08_Crime_Files_16x9").max_total_seconds, 300.0)


class TestQuizTiming(unittest.TestCase):
    def setUp(self):
        self.wf = GeneralQuizWorkflow()
        self.plan = self.wf.plan(example_content("general_quiz"))

    def test_intro_questions_then_score(self):
        self.assertEqual([s.kind for s in self.plan.slides], ["intro"] + ["question"] * 4 + ["score"])

    def test_answer_is_revealed_inside_the_slide(self):
        for q in self.plan.slides[1:-1]:
            self.assertIn("reveal", q.data)
            self.assertLess(q.data["reveal"] / 1000, q.duration)
            self.assertIn("answer shown at", q.reason)

    def test_populate_keeps_reveal_and_options(self):
        _, intro, slides = populated_data(self.wf, self.plan)
        self.assertEqual(intro["title"], "Can You Score 4/4?")
        self.assertEqual(len(slides), 4)
        self.assertEqual(len(slides[0]["options"]), 4)
        self.assertEqual(slides[0]["reveal"], self.plan.slides[1].data["reveal"])

    def test_needs_four_options(self):
        with self.assertRaises(ValueError):
            self.wf.plan({"intro": {"title": "T"}, "slides": [{"question": "Q", "options": ["a", "b"], "correct": "A"}]})

    def test_science_quiz_is_a_quiz(self):
        self.assertIsInstance(get_workflow("04_Science_Quiz_9x16"), QuizWorkflow)


class TestTypedTiming(unittest.TestCase):
    def test_slide_changes_right_after_typing(self):
        wf = get_workflow("14_AI_Neural_Intelligence_16x9")
        self.assertIsInstance(wf, TypedWorkflow)
        slides = [{"section": "S", "title": "T", "narration": "x" * 100} for _ in range(4)]  # 2.7s typing
        plan = wf.plan({"intro": {"title": "T"}, "slides": slides})
        self.assertEqual(plan.slides[1].duration, 4.3)

    def test_exactly_four_scenes(self):
        wf = get_workflow("14_AI_Neural_Intelligence_16x9")
        with self.assertRaises(ValueError):
            wf.plan({"intro": {"title": "T"}, "slides": [{"section": "S", "title": "T", "narration": "N"}] * 3})

    def test_digital_future_needs_seven_bars(self):
        wf = AIDigitalFutureWorkflow()
        slide = {"section": "S", "title": "T", "narration": "N", "metric": "M", "desc": "D", "bars": [1, 2, 3]}
        with self.assertRaises(ValueError):
            wf.plan({"intro": {"title": "T"}, "slides": [slide] * 4})
        plan = wf.plan(example_content("ai_digital_future"))
        _, _, slides = populated_data(wf, plan)
        self.assertEqual(len(slides[0]["bars"]), 7)


class TestPopulateSafety(unittest.TestCase):
    def test_script_close_is_escaped(self):
        wf = ScienceStoryWorkflow()
        plan = wf.plan({"intro": {"title": "</script>"}, "slides": [{"chapter": "A", "title": "B", "text": "C"}]})
        html, _ = wf.loader.load(wf.template_id)
        self.assertNotIn('</script>"', wf.populate(html, plan))

    def test_base_class_is_abstract_enough(self):
        self.assertTrue(issubclass(QuizWorkflow, SlideWorkflow))


if __name__ == "__main__":
    unittest.main()
