"""Video orchestration - connects renderer and encoder to run artifacts."""

import os
import json
import logging
import tempfile
import shutil
from typing import Optional, Dict, Any, List

from core.run_config import RunConfig
from core.manifest import Manifest
from rendering.browser_renderer import BrowserRenderer
from rendering.video_encoder import FFmpegEncoder

logger = logging.getLogger(__name__)

DEFAULT_DURATION = 5.0
DEFAULT_SCENE_COUNT = 6


class VideoOrchestrator:
    def __init__(
        self,
        run_dir: str,
        ffmpeg_path: str = None,
        fps: int = 30,
        duration: float = DEFAULT_DURATION,
        scene_count: int = DEFAULT_SCENE_COUNT,
        scene_timings: List[float] = None,
        headless: bool = True,
    ):
        self.run_dir = run_dir
        self.ffmpeg_path = ffmpeg_path
        self.fps = fps
        self.duration = duration
        self.scene_count = scene_count
        self.scene_timings = scene_timings
        self.headless = headless
        self.renderer: Optional[BrowserRenderer] = None
        self.encoder: Optional[FFmpegEncoder] = None

    def run(self) -> Dict[str, Any]:
        populated_path = os.path.join(self.run_dir, "populated.html")
        if not os.path.isfile(populated_path):
            return {"success": False, "error": f"populated.html not found in {self.run_dir}"}

        manifest_path = os.path.join(self.run_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            return {"success": False, "error": f"manifest.json not found in {self.run_dir}"}

        frame_paths = []
        renderer = None
        render_result = {}
        validation = {}
        video_dir = ""

        try:
            try:
                renderer = BrowserRenderer.from_manifest(
                    manifest_path,
                    fps=self.fps,
                    headless=self.headless,
                )
            except Exception as e:
                return {"success": False, "error": f"Browser renderer initialization failed: {e}"}

            video_dir = os.path.join(self.run_dir, "video")
            os.makedirs(video_dir, exist_ok=True)
            final_mp4 = os.path.join(video_dir, "final.mp4")

            try:
                renderer._ensure_browser()
            except RuntimeError as e:
                return {"success": False, "error": f"Browser renderer failed: {e}"}

            try:
                with renderer as r:
                    try:
                        render_result = r.render(
                            html_content=open(populated_path, "r", encoding="utf-8").read(),
                            output_dir=self.run_dir,
                            duration=self.duration,
                            scene_count=self.scene_count,
                            scene_timings=self.scene_timings,
                        )
                        frame_paths = render_result.get("frame_paths", [])
                    except RuntimeError as e:
                        return {"success": False, "error": f"Rendering failed: {e}"}

                    try:
                        encoder = FFmpegEncoder(ffmpeg_path=self.ffmpeg_path, fps=self.fps)
                        encoder.encode_frames(
                            frames=frame_paths,
                            output_path=final_mp4,
                            width=renderer.width,
                            height=renderer.height,
                        )
                    except Exception as e:
                        return {"success": False, "error": f"Encoding failed: {e}"}

                    try:
                        validation = encoder.validate(
                            final_mp4,
                            expected_width=renderer.width,
                            expected_height=renderer.height,
                        )
                    except Exception as e:
                        validation = {"valid": False, "error": str(e)}

                    result = {
                        "success": True,
                        "video_path": final_mp4,
                        "video_dir": video_dir,
                        "renderer": {
                            "width": renderer.width,
                            "height": renderer.height,
                            "aspect_ratio": renderer.aspect_ratio,
                            "fps": self.fps,
                        },
                        "encoder": {"fps": self.fps, "format": "mp4"},
                        "render": render_result,
                        "validation": validation,
                        "frames_captured": len(frame_paths),
                    }
                    return result

            finally:
                if renderer:
                    renderer.close()

        finally:
            frames_dir = os.path.join(self.run_dir, "frames")
            if os.path.isdir(frames_dir):
                shutil.rmtree(frames_dir, ignore_errors=True)
