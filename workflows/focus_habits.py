"""Workflow for 01_Focus_Habits_Shorts_9x16.

Content shape:
    {
      "intro": {"kicker": "...", "title": "...", "text": "...", "micro": "..."},
      "slides": [{"title": "...", "text": "...", "duration": 6.0 (optional)}, ...]
    }

Timing rules (template types each slide's text at 28 ms per character):
    intro:  entry + reading(title, text) + hold, 2.5-5s
    habit:  entry + reading(title) + max(typing(text), reading(text)) + hold, 3-10s
A "duration" given on a slide overrides the rule (still clamped to the range).
"""

import re
from typing import Any, Dict

from workflows.base import SlidePlan, TemplateWorkflow, WorkflowPlan, to_js_literal
from workflows.timing import clamp_seconds, reading_seconds, typing_seconds, word_count

TYPING_MS_PER_CHAR = 28
ENTRY_SECONDS = 0.6
HOLD_SECONDS = 1.0
INTRO_RANGE = (2.5, 5.0)
HABIT_RANGE = (3.0, 10.0)


class FocusHabitsWorkflow(TemplateWorkflow):
    template_id = "01_Focus_Habits_Shorts_9x16"
    aspect_ratio = "9:16"
    max_total_seconds = 60.0

    def plan(self, content: Dict[str, Any]) -> WorkflowPlan:
        intro = content.get("intro") or {}
        slides = content.get("slides") or []
        if not intro.get("title"):
            raise ValueError("intro.title is required")
        if not slides:
            raise ValueError("at least one slide is required")
        for i, s in enumerate(slides):
            if not s.get("title") or not s.get("text"):
                raise ValueError(f"slide {i + 1} needs both title and text")

        plan = WorkflowPlan(template_id=self.template_id, aspect_ratio=self.aspect_ratio)
        intro_data = {
            "kicker": intro.get("kicker", ""),
            "title": intro["title"],
            "text": intro.get("text", ""),
            "micro": intro.get("micro", ""),
        }
        duration, reason = self._intro_duration(intro_data, intro.get("duration"))
        plan.slides.append(SlidePlan(0, "intro", intro_data, duration, reason))

        for i, s in enumerate(slides, start=1):
            data = {"title": s["title"], "text": s["text"]}
            duration, reason = self._habit_duration(data, s.get("duration"))
            plan.slides.append(SlidePlan(i, "habit", data, duration, reason))
        return plan

    def _intro_duration(self, data, override):
        if override is not None:
            return clamp_seconds(float(override), *INTRO_RANGE), "manual override"
        read = reading_seconds(data["title"], data["text"])
        raw = ENTRY_SECONDS + read + HOLD_SECONDS
        reason = (
            f"{word_count(data['title'], data['text'])} words to read ({read:.1f}s) "
            f"+ {ENTRY_SECONDS}s entry + {HOLD_SECONDS}s hold"
        )
        return _clamped(raw, INTRO_RANGE, reason)

    def _habit_duration(self, data, override):
        if override is not None:
            return clamp_seconds(float(override), *HABIT_RANGE), "manual override"
        title_read = reading_seconds(data["title"])
        typing = typing_seconds(data["text"], TYPING_MS_PER_CHAR)
        text_read = reading_seconds(data["text"])
        raw = ENTRY_SECONDS + title_read + max(typing, text_read) + HOLD_SECONDS
        limiter = "reading" if text_read >= typing else "typing"
        reason = (
            f"title {title_read:.1f}s + text {max(typing, text_read):.1f}s ({limiter}, "
            f"{word_count(data['text'])} words / {len(data['text'])} chars) "
            f"+ {ENTRY_SECONDS}s entry + {HOLD_SECONDS}s hold"
        )
        return _clamped(raw, HABIT_RANGE, reason)

    def populate(self, html: str, plan: WorkflowPlan) -> str:
        intro, habits = plan.slides[0], plan.slides[1:]
        intro_js = to_js_literal({**intro.data, "duration": intro.duration})
        slides_js = to_js_literal([{**s.data, "duration": s.duration} for s in habits])
        html = _replace_const(html, "introData", r"\{.*?\}", intro_js)
        return _replace_const(html, "slidesData", r"\[.*?\]", slides_js)


def _clamped(raw, limits, reason):
    duration = clamp_seconds(raw, *limits)
    if duration != round(raw, 1):
        reason += f" = {raw:.1f}s, limited to {duration}s"
    return duration, reason


def _replace_const(html: str, name: str, value_pattern: str, value: str) -> str:
    pattern = rf"const\s+{name}\s*=\s*{value_pattern}\s*;"
    replaced, count = re.subn(pattern, lambda _: f"const {name}={value};", html, count=1, flags=re.DOTALL)
    if count != 1:
        raise ValueError(f"template is missing 'const {name}=...;'")
    return replaced
