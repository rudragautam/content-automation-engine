"""Base class for per-template workflows.

Each template owns a workflow that knows the template's slide structure,
decides how long every slide stays on screen, fills the template, and
renders it to video on a frame-accurate timeline.
"""

import json
import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from templates.loader import TemplateLoader

logger = logging.getLogger(__name__)


@dataclass
class SlidePlan:
    index: int
    kind: str
    data: Dict[str, Any]
    duration: float
    reason: str


@dataclass
class WorkflowPlan:
    template_id: str
    aspect_ratio: str
    slides: List[SlidePlan] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return round(sum(s.duration for s in self.slides), 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "aspect_ratio": self.aspect_ratio,
            "total_seconds": self.total_seconds,
            "slides": [asdict(s) for s in self.slides],
        }


class TemplateWorkflow(ABC):
    template_id: str = ""
    aspect_ratio: str = "9:16"
    max_total_seconds: Optional[float] = None

    def __init__(self, loader: TemplateLoader = None):
        self.loader = loader or TemplateLoader()

    @abstractmethod
    def plan(self, content: Dict[str, Any]) -> WorkflowPlan:
        """Validate content and decide every slide's duration."""

    @abstractmethod
    def populate(self, html: str, plan: WorkflowPlan) -> str:
        """Write the planned slides into the template HTML."""

    def validate(self, plan: WorkflowPlan) -> List[str]:
        errors = []
        if not plan.slides:
            errors.append("workflow produced no slides")
        if self.max_total_seconds and plan.total_seconds > self.max_total_seconds:
            errors.append(
                f"video is {plan.total_seconds}s, over the {self.max_total_seconds}s limit "
                f"for {self.template_id}; remove slides or shorten text"
            )
        return errors

    def run(
        self,
        content: Dict[str, Any],
        output_dir: str = "output/runs",
        render: bool = True,
        fps: int = 30,
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())[:12]
        run_dir = os.path.join(output_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)

        try:
            plan = self.plan(content)
        except ValueError as e:
            return {"run_id": run_id, "success": False, "error": str(e)}

        errors = self.validate(plan)
        if errors:
            return {"run_id": run_id, "success": False, "error": "; ".join(errors), "timeline": plan.to_dict()}

        html, _ = self.loader.load(self.template_id)
        populated = self.populate(html, plan)
        populated_path = os.path.join(run_dir, "populated.html")
        self._write(populated_path, populated)
        timeline_path = os.path.join(run_dir, "timeline.json")
        self._write(timeline_path, json.dumps(plan.to_dict(), indent=2, ensure_ascii=False))

        result = {
            "run_id": run_id,
            "output_dir": run_dir,
            "template_id": self.template_id,
            "populated_html": populated_path,
            "timeline": timeline_path,
            "total_seconds": plan.total_seconds,
            "success": True,
        }
        if render:
            result["video"] = self._render(populated, plan, run_dir, fps)
            result["success"] = result["video"].get("success", False)
        return result

    def _render(self, html: str, plan: WorkflowPlan, run_dir: str, fps: int) -> Dict[str, Any]:
        from rendering.timeline_renderer import TimelineRenderer
        from rendering.video_encoder import FFmpegEncoder

        video_path = os.path.join(run_dir, "video", "final.mp4")
        renderer = TimelineRenderer(aspect_ratio=plan.aspect_ratio, fps=fps)
        try:
            encoder = FFmpegEncoder(fps=fps)
            frames = renderer.capture(html, [s.duration for s in plan.slides], os.path.join(run_dir, "frames"))
            encoder.encode_frames(frames, video_path, renderer.width, renderer.height)
            validation = encoder.validate(
                video_path,
                expected_width=renderer.width,
                expected_height=renderer.height,
                expected_duration=plan.total_seconds,
            )
        except Exception as e:
            return {"success": False, "error": f"Rendering failed: {e}"}
        finally:
            renderer.cleanup()
        return {
            "success": validation.get("valid", False),
            "video_path": video_path,
            "frames": len(frames),
            "validation": validation,
        }

    @staticmethod
    def _write(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("Wrote %s (%d bytes)", path, len(content))


def to_js_literal(value: Any) -> str:
    """JSON for embedding inside a <script> block."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def replace_const(html: str, name: str, value: str) -> str:
    """Swap the value of a top-level `const name = {...};` or `const name = [...];` in the template script."""
    pattern = rf"const\s+{name}\s*=\s*(?:\{{.*?\}}|\[.*?\])\s*;"
    replaced, count = re.subn(pattern, lambda _: f"const {name}={value};", html, count=1, flags=re.DOTALL)
    if count != 1:
        raise ValueError(f"template is missing 'const {name}=...;'")
    return replaced
