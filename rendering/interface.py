"""Rendering interface - abstraction for HTML-to-video rendering."""

from abc import ABC, abstractmethod
from typing import Optional


class Renderer(ABC):
    @abstractmethod
    def render(self, html_content: str) -> bytes:
        pass

    @abstractmethod
    def get_metadata(self, html_content: str) -> dict:
        pass


class RenderPreview(ABC):
    @abstractmethod
    def preview(self, html_content: str) -> str:
        pass


class TimingExtractor(ABC):
    @abstractmethod
    def extract_timings(self, html_content: str) -> dict:
        pass


class RenderConfig:
    def __init__(
        self,
        output_format: str = "mp4",
        fps: int = 30,
        width: Optional[int] = None,
        height: Optional[int] = None,
        preserve_animations: bool = True,
        preserve_transitions: bool = True,
        preserve_javascript: bool = True,
    ):
        self.output_format = output_format
        self.fps = fps
        self.width = width
        self.height = height
        self.preserve_animations = preserve_animations
        self.preserve_transitions = preserve_transitions
        self.preserve_javascript = preserve_javascript
