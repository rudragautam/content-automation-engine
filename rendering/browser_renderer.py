"""Browser renderer using Playwright for HTML-to-frame capture."""

import os
import json
import logging
import tempfile
import time
from typing import Optional, List, Dict, Any, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, Playwright
except ImportError:
    Playwright = None

DEFAULT_VIEWPORTS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}


def get_viewport_dimensions(aspect_ratio: str) -> Tuple[int, int]:
    if aspect_ratio not in DEFAULT_VIEWPORTS:
        raise ValueError(
            f"Unsupported aspect ratio: {aspect_ratio}. "
            f"Supported: {list(DEFAULT_VIEWPORTS.keys())}"
        )
    return DEFAULT_VIEWPORTS[aspect_ratio]


class BrowserRenderer:
    def __init__(
        self,
        width: int = None,
        height: int = None,
        aspect_ratio: str = None,
        fps: int = 30,
        wait_for_timeout: int = 3000,
        headless: bool = True,
    ):
        self.fps = fps
        self.headless = headless
        self.wait_for_timeout = wait_for_timeout
        self.playwright: Optional[Playwright] = None
        self.browser = None

        if width and height:
            self.width = width
            self.height = height
            self.aspect_ratio = aspect_ratio or self._detect_aspect(width, height)
        elif aspect_ratio:
            self.width, self.height = get_viewport_dimensions(aspect_ratio)
            self.aspect_ratio = aspect_ratio
        else:
            raise ValueError("Either (width, height) or aspect_ratio must be provided")

    @staticmethod
    def _detect_aspect(width: int, height: int) -> str:
        if width == 1080 and height == 1920:
            return "9:16"
        if width == 1920 and height == 1080:
            return "16:9"
        if width == 1080 and height == 1080:
            return "1:1"
        return "16:9"

    def _ensure_browser(self):
        if Playwright is None:
            raise RuntimeError(
                "Playwright not installed. Install with: pip install playwright && "
                "python -m playwright install chromium"
            )
        if self.browser is None:
            self.playwright = sync_playwright().start()
            launch_opts = {"headless": self.headless}
            if os.name == "nt":
                launch_opts["args"] = ["--no-sandbox", "--disable-setuid-sandbox"]
            self.browser = self.playwright.chromium.launch(**launch_opts)

    def close(self):
        if self.browser:
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None

    def __enter__(self):
        self._ensure_browser()
        return self

    def __exit__(self, *args):
        self.close()

    def render(
        self,
        html_content: str,
        output_dir: str,
        duration: float = 5.0,
        scene_count: int = None,
        scene_timings: List[float] = None,
    ) -> Dict[str, Any]:
        self._ensure_browser()
        os.makedirs(output_dir, exist_ok=True)

        context = self.browser.new_context(
            viewport={"width": self.width, "height": self.height},
            device_scale_factor=1,
        )
        page = context.new_page()

        page.set_content(html_content, wait_until="load")
        page.wait_for_timeout(self.wait_for_timeout)

        frames_dir = os.path.join(output_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        frame_paths = []

        if scene_timings:
            timings = scene_timings
        elif scene_count:
            interval = duration / scene_count
            timings = [i * interval for i in range(scene_count)]
        else:
            interval = duration / max(4, self.fps // 2)
            timings = [i * interval for i in range(int(duration * self.fps // 2))]

        for i, t in enumerate(timings):
            if t > 0:
                page.wait_for_timeout(int((t - (timings[i - 1] if i > 0 else 0)) * 1000))

            frame_path = os.path.join(frames_dir, f"frame_{i:04d}.png")
            page.screenshot(path=frame_path, full_page=False)
            frame_paths.append(frame_path)
            logger.info("Captured frame %d/%d at t=%.2fs", i + 1, len(timings), t)

        context.close()

        return {
            "frame_paths": frame_paths,
            "frame_count": len(frame_paths),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": duration,
        }

    def render_single(
        self,
        html_content: str,
        output_path: str,
    ) -> str:
        self._ensure_browser()
        context = self.browser.new_context(
            viewport={"width": self.width, "height": self.height},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.set_content(html_content, wait_until="load")
        page.wait_for_timeout(self.wait_for_timeout)
        page.screenshot(path=output_path, full_page=False)
        context.close()
        return output_path

    @classmethod
    def from_manifest(
        cls,
        manifest_path: str,
        fps: int = 30,
        headless: bool = True,
    ) -> "BrowserRenderer":
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        aspect = manifest.get("aspect_ratio", "16:9")
        width, height = get_viewport_dimensions(aspect)
        return cls(
            width=width,
            height=height,
            aspect_ratio=aspect,
            fps=fps,
            headless=headless,
        )
