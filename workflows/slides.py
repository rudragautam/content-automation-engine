"""Workflows for the data-driven slide templates (02-08, 14, 15).

Every one of these templates takes an `introData` object and one array of
slides, and exposes `window.__engine.goTo(index, ms)` so the renderer can
drive it slide by slide with the planned duration.

Content shape (what the Excel templates and Gemini produce):
    {"intro": {...intro fields...}, "slides": [{...slide fields...}, ...]}

Timing rules:
    story scene:   entry + reading(chapter, title, text) + hold
    quiz question: entry + reading(question, options) + think, then the answer
                   is revealed, + reading(explanation) + hold
    typed scene:   entry + typing(narration at 27 ms/char) + hold
A "duration" on a slide overrides the rule (still clamped to the range).
"""

from typing import Any, Dict, List, Optional, Tuple

from workflows.base import SlidePlan, TemplateWorkflow, WorkflowPlan, replace_const, to_js_literal
from workflows.timing import clamp_seconds, reading_seconds, typing_seconds, word_count

ENTRY_SECONDS = 0.6
HOLD_SECONDS = 1.2
INTRO_RANGE = (2.5, 6.0)
# YouTube Shorts may run up to 3 minutes; 16:9 videos get a little more room.
MAX_SECONDS = {"9:16": 180.0, "16:9": 300.0}


class SlideWorkflow(TemplateWorkflow):
    """Intro slide plus one slide per content item, written into `data_var`."""

    data_var = "slidesData"
    slide_kind = "scene"
    slide_range = (3.0, 12.0)
    required_intro = ("title",)
    required_slide = ("title", "text")
    min_slides = 1
    max_slides: Optional[int] = None

    def __init__(self, loader=None):
        super().__init__(loader)
        self.max_total_seconds = MAX_SECONDS[self.aspect_ratio]

    def plan(self, content: Dict[str, Any]) -> WorkflowPlan:
        intro = dict(content.get("intro") or {})
        slides = [dict(s) for s in content.get("slides") or []]
        for key in self.required_intro:
            if not intro.get(key):
                raise ValueError(f"intro.{key} is required")
        if len(slides) < self.min_slides:
            raise ValueError(f"at least {self.min_slides} slide{'s' if self.min_slides > 1 else ''} required")
        if self.max_slides and len(slides) > self.max_slides:
            raise ValueError(f"this template takes at most {self.max_slides} slides")
        for i, s in enumerate(slides):
            for key in self.required_slide:
                if not s.get(key):
                    raise ValueError(f"slide {i + 1} needs {key}")

        plan = WorkflowPlan(template_id=self.template_id, aspect_ratio=self.aspect_ratio)
        override = intro.pop("duration", None)
        duration, reason = self._intro_duration(intro, override)
        plan.slides.append(SlidePlan(0, "intro", intro, duration, reason))
        for i, s in enumerate(slides, start=1):
            override = s.pop("duration", None)
            duration, reason = self._slide_duration(s, override)
            plan.slides.append(SlidePlan(i, self.slide_kind, s, duration, reason))
        self._add_closing(plan)
        return plan

    def _add_closing(self, plan: WorkflowPlan) -> None:
        """Templates with a slide after the items (the quiz score) add it here."""

    def _intro_duration(self, data: Dict[str, Any], override) -> Tuple[float, str]:
        if override is not None:
            return clamp_seconds(float(override), *INTRO_RANGE), "manual override"
        texts = [str(v) for k, v in data.items() if k != "image"]
        read = reading_seconds(*texts)
        reason = f"{word_count(*texts)} words to read ({read:.1f}s) + {ENTRY_SECONDS}s entry + {HOLD_SECONDS}s hold"
        return _clamped(ENTRY_SECONDS + read + HOLD_SECONDS, INTRO_RANGE, reason)

    def _slide_duration(self, data: Dict[str, Any], override) -> Tuple[float, str]:
        if override is not None:
            return clamp_seconds(float(override), *self.slide_range), "manual override"
        texts = [data.get(k, "") for k in self.read_keys(data)]
        read = reading_seconds(*texts)
        reason = f"{word_count(*texts)} words to read ({read:.1f}s) + {ENTRY_SECONDS}s entry + {HOLD_SECONDS}s hold"
        return _clamped(ENTRY_SECONDS + read + HOLD_SECONDS, self.slide_range, reason)

    def read_keys(self, data: Dict[str, Any]) -> List[str]:
        return [k for k in ("chapter", "title", "text") if k in data]

    def populate(self, html: str, plan: WorkflowPlan) -> str:
        intro, items = plan.slides[0], [s for s in plan.slides[1:] if s.kind == self.slide_kind]
        html = replace_const(html, "introData", to_js_literal({**intro.data, "duration": intro.duration}))
        return replace_const(html, self.data_var, to_js_literal([self.slide_js(s) for s in items]))

    def slide_js(self, slide: SlidePlan) -> Dict[str, Any]:
        return {**slide.data, "duration": slide.duration}


# ---------- stories ----------

class GeetaGyaanWorkflow(SlideWorkflow):
    template_id = "02_Geeta_Gyaan_9x16"
    aspect_ratio = "9:16"
    data_var = "slidesData"
    slide_kind = "lesson"


class ScienceStoryWorkflow(SlideWorkflow):
    template_id = "05_Science_Storytelling_9x16"
    aspect_ratio = "9:16"
    data_var = "storyData"


class IndianTraditionalStoryWorkflow(SlideWorkflow):
    template_id = "06_Indian_Traditional_Story_9x16"
    aspect_ratio = "9:16"
    data_var = "storyData"


class IndianHeritageStoryWorkflow(SlideWorkflow):
    template_id = "07_Indian_Heritage_Story_16x9"
    aspect_ratio = "16:9"
    data_var = "storyData"
    slide_range = (4.0, 14.0)


class CrimeFilesWorkflow(SlideWorkflow):
    template_id = "08_Crime_Files_16x9"
    aspect_ratio = "16:9"
    data_var = "crimeData"
    slide_range = (4.0, 14.0)


# ---------- quizzes ----------

THINK_SECONDS = 2.5
SCORE_SECONDS = 3.5
QUIZ_RANGE = (5.0, 16.0)


class QuizWorkflow(SlideWorkflow):
    """Intro, one slide per question (answer revealed mid-slide), then a score slide."""

    data_var = "quizData"
    slide_kind = "question"
    slide_range = QUIZ_RANGE
    required_slide = ("question", "options", "correct")

    def _slide_duration(self, data: Dict[str, Any], override) -> Tuple[float, str]:
        options = [str(o) for o in data.get("options") or []]
        if len(options) != 4:
            raise ValueError("every question needs exactly 4 options")
        ask = ENTRY_SECONDS + reading_seconds(data.get("question", ""), *options) + THINK_SECONDS
        data["reveal"] = round(ask * 1000)
        if override is not None:
            return clamp_seconds(float(override), *self.slide_range), "manual override"
        answer = reading_seconds(data.get("explanation", "")) + HOLD_SECONDS
        reason = (f"question and options read ({ask - THINK_SECONDS - ENTRY_SECONDS:.1f}s) + {ENTRY_SECONDS}s entry "
                  f"+ {THINK_SECONDS}s to think, answer shown at {ask:.1f}s, then explanation ({answer - HOLD_SECONDS:.1f}s) + {HOLD_SECONDS}s hold")
        return _clamped(ask + answer, self.slide_range, reason)

    def _add_closing(self, plan: WorkflowPlan) -> None:
        plan.slides.append(SlidePlan(len(plan.slides), "score", {}, SCORE_SECONDS, "closing score slide"))


class GeneralQuizWorkflow(QuizWorkflow):
    template_id = "03_General_Quiz_9x16"
    aspect_ratio = "9:16"


class ScienceQuizWorkflow(QuizWorkflow):
    template_id = "04_Science_Quiz_9x16"
    aspect_ratio = "9:16"


# ---------- typed narration (AI series) ----------

TYPING_MS_PER_CHAR = 27
TYPED_HOLD_SECONDS = 1.0
TYPED_RANGE = (4.0, 14.0)


class TypedWorkflow(SlideWorkflow):
    """Each slide types its narration out; it changes once the typing is done."""

    data_var = "aiData"
    slide_kind = "scene"
    slide_range = TYPED_RANGE
    required_slide = ("title", "narration")
    min_slides = 4
    max_slides = 4

    def _slide_duration(self, data: Dict[str, Any], override) -> Tuple[float, str]:
        if override is not None:
            return clamp_seconds(float(override), *self.slide_range), "manual override"
        typing = typing_seconds(data["narration"], TYPING_MS_PER_CHAR)
        reason = f"typing {typing:.1f}s ({len(data['narration'])} chars) + {ENTRY_SECONDS}s entry + {TYPED_HOLD_SECONDS}s hold"
        return _clamped(ENTRY_SECONDS + typing + TYPED_HOLD_SECONDS, self.slide_range, reason)


class AINeuralIntelligenceWorkflow(TypedWorkflow):
    template_id = "14_AI_Neural_Intelligence_16x9"
    aspect_ratio = "16:9"


class AIDigitalFutureWorkflow(TypedWorkflow):
    template_id = "15_AI_Digital_Future_16x9"
    aspect_ratio = "16:9"

    def plan(self, content):
        for i, s in enumerate(content.get("slides") or []):
            bars = s.get("bars")
            if not isinstance(bars, list) or len(bars) != 7:
                raise ValueError(f"slide {i + 1} needs 7 bar values")
        return super().plan(content)


def _clamped(raw, limits, reason):
    duration = clamp_seconds(raw, *limits)
    if duration != round(raw, 1):
        reason += f" = {raw:.1f}s, limited to {duration}s"
    return duration, reason
