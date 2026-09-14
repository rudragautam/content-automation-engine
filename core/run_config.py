"""Run configuration for end-to-end engine execution."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.content_mode import ContentMode


@dataclass
class RunConfig:
    mode: ContentMode = ContentMode.AUTO
    topic: str = ""
    storyline: Tuple[str, ...] = ()
    key_points: Tuple[str, ...] = ()
    platform: str = "youtube_short"
    content_format: str = "short_video"
    aspect_ratio: str = ""
    template_id: Optional[str] = None
    template_filename: Optional[str] = None
    assets: Dict[str, str] = field(default_factory=dict)
    theme: Dict[str, str] = field(default_factory=dict)
    output_dir: str = "output/runs"
    output_filename: Optional[str] = None
    research_settings: Optional[Dict[str, Any]] = None

    def validate(self) -> List[str]:
        errors = []
        if self.mode not in (ContentMode.AUTO, ContentMode.CUSTOM, ContentMode.HYBRID):
            errors.append(f"invalid mode: {self.mode}")
        if not self.topic and self.mode == ContentMode.CUSTOM and not self.storyline and not self.key_points:
            errors.append("CUSTOM mode requires topic, storyline, or key_points")
        effective_aspect = self.aspect_ratio if self.aspect_ratio else "9:16"
        if effective_aspect not in ("9:16", "16:9", "1:1"):
            errors.append(f"unsupported aspect ratio: {self.aspect_ratio}")
        if self.template_id and self.template_filename:
            if (not self.template_id.endswith(".html") and
                not self.template_filename.endswith(".html") and
                self.template_id != self.template_filename):
                errors.append("template_id or template_filename should be .html")
        return errors

    def get_aspect_from_platform(self) -> str:
        if self.aspect_ratio:
            return self.aspect_ratio
        if self.platform == "youtube_short":
            return "9:16"
        return "16:9"
