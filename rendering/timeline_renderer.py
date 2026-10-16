"""Frame-accurate renderer that drives a template slide by slide.

The page runs on Playwright's paused virtual clock and every CSS animation
is paused and advanced manually, so each captured frame is exactly
1/fps seconds after the previous one no matter how slow screenshots are.

Templates must expose `window.__engine = {count, goTo(index, ms)}`; `ms` is the
slide's planned duration, for progress bars and timed reveals.
"""

import logging
import os
import shutil
from typing import List

from rendering.browser_renderer import Playwright, get_viewport_dimensions

logger = logging.getLogger(__name__)

# Templates are designed for real screens (a phone for 9:16), so lay them out at that
# CSS size and multiply pixel density to reach the output resolution.
DEVICE_SCALE = {"9:16": 3, "16:9": 1.5, "1:1": 2}

_ADVANCE_ANIMATIONS ="""ms => document.getAnimations().forEach(a => {
    a.pause();
    a.currentTime = (a.currentTime || 0) + ms;
})"""


class TimelineRenderer:
    def __init__(self, aspect_ratio: str = "9:16", fps: int = 30, headless: bool = True, jpeg_quality: int = 92):
        self.width, self.height = get_viewport_dimensions(aspect_ratio)
        self.scale = DEVICE_SCALE[aspect_ratio]
        self.fps = fps
        self.headless = headless
        self.jpeg_quality = jpeg_quality
        self._frames_dir = None

    def capture(self, html: str, durations: List[float], frames_dir: str) -> List[str]:
        if Playwright is None:
            raise RuntimeError(
                "Playwright not installed. Install with: pip install playwright && "
                "python -m playwright install chromium"
            )
        from playwright.sync_api import sync_playwright

        self._frames_dir = frames_dir
        os.makedirs(frames_dir, exist_ok=True)
        frame_ms = 1000 / self.fps
        frame_paths: List[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                page = browser.new_page(
                    viewport={"width": round(self.width / self.scale), "height": round(self.height / self.scale)},
                    device_scale_factor=self.scale,
                )
                page.clock.install(time=0)
                page.clock.pause_at(1000)
                page.set_content(html, wait_until="load")
                page.evaluate("document.fonts.ready")

                slide_count = page.evaluate("window.__engine ? window.__engine.count : -1")
                if slide_count < 0:
                    raise RuntimeError("template does not expose window.__engine")
                if slide_count != len(durations):
                    raise RuntimeError(f"template has {slide_count} slides but {len(durations)} durations were planned")

                for index, seconds in enumerate(durations):
                    page.evaluate("([i, ms]) => window.__engine.goTo(i, ms)", [index, round(seconds * 1000)])
                    page.evaluate(_ADVANCE_ANIMATIONS, 0)
                    for _ in range(round(seconds * self.fps)):
                        n = len(frame_paths)
                        path = os.path.join(frames_dir, f"frame_{n:05d}.jpg")
                        page.screenshot(path=path, type="jpeg", quality=self.jpeg_quality)
                        frame_paths.append(path)
                        # The clock only takes whole milliseconds; alternate 33/34 ms at 30 fps so time never drifts.
                        step_ms = round((n + 1) * frame_ms) - round(n * frame_ms)
                        page.clock.run_for(step_ms)
                        page.evaluate(_ADVANCE_ANIMATIONS, step_ms)
                    logger.info("Slide %d: %.1fs captured (%d frames total)", index, seconds, len(frame_paths))
            finally:
                browser.close()
        return frame_paths

    def cleanup(self) -> None:
        if self._frames_dir and os.path.isdir(self._frames_dir):
            shutil.rmtree(self._frames_dir, ignore_errors=True)
