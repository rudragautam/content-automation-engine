"""Video encoder using FFmpeg for frame-to-MP4 encoding."""

import subprocess
import logging
import os
import tempfile
import shutil
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


try:
    import imageio_ffmpeg

    _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    _FFMPEG_PATH = None


def get_ffmpeg_path() -> str:
    if _FFMPEG_PATH and os.path.isfile(_FFMPEG_PATH):
        return _FFMPEG_PATH
    raise RuntimeError(
        "FFmpeg not found. Install imageio-ffmpeg: pip install imageio-ffmpeg, "
        "or install FFmpeg manually from https://ffmpeg.org/download.html"
    )


class FFmpegEncoder:
    def __init__(
        self,
        ffmpeg_path: str = None,
        fps: int = 30,
        output_format: str = "mp4",
    ):
        self.ffmpeg_path = ffmpeg_path or get_ffmpeg_path()
        self.fps = fps
        self.output_format = output_format

    def encode_frames(
        self,
        frames: List[str],
        output_path: str,
        width: int,
        height: int,
    ) -> str:
        if not frames:
            raise ValueError("No frames to encode")
        if not os.path.isfile(self.ffmpeg_path):
            raise RuntimeError(
                f"FFmpeg binary not found at: {self.ffmpeg_path}. "
                "Install imageio-ffmpeg: pip install imageio-ffmpeg"
            )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        fps_pipe = None
        try:
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-f", "image2pipe",
                "-r", str(self.fps),
                "-i", "-",
                "-vf", f"scale={width}:{height}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "23",
                "-movflags", "+faststart",
                output_path,
            ]
            logger.info("Running FFmpeg: %s", " ".join(cmd[:4]) + " ...")
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for frame_path in frames:
                with open(frame_path, "rb") as f:
                    proc.stdin.write(f.read())
            proc.stdin.close()
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")[-500:]
                raise RuntimeError(
                    f"FFmpeg encoding failed (exit {proc.returncode}): {error_msg}"
                )
            logger.info("FFmpeg encoding complete: %s", output_path)
        finally:
            if fps_pipe:
                fps_pipe.close()

        if not os.path.isfile(output_path):
            raise RuntimeError(f"FFmpeg did not produce output: {output_path}")
        return output_path

    def get_metadata(self, video_path: str) -> dict:
        cmd = [self.ffmpeg_path, "-hide_banner", "-i", video_path]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        _, stderr = proc.communicate()
        output = stderr.decode("utf-8", errors="replace")
        metadata = {
            "path": video_path,
            "exists": os.path.isfile(video_path),
            "size": os.path.getsize(video_path) if os.path.isfile(video_path) else 0,
        }
        for line in output.split("\n"):
            if "Video:" in line:
                metadata["video_info"] = line.strip()
                break
        return metadata

    def validate(self, video_path: str, expected_width: int = None, expected_height: int = None) -> dict:
        if not os.path.isfile(video_path):
            return {"valid": False, "error": "Video file does not exist"}
        size = os.path.getsize(video_path)
        if size == 0:
            return {"valid": False, "error": "Video file is empty"}
        try:
            metadata = self.get_metadata(video_path)
        except Exception as e:
            return {"valid": False, "error": f"FFmpeg metadata error: {e}"}

        result = {"valid": True, "size": size, "metadata": metadata}
        if expected_width or expected_height:
            info = metadata.get("video_info", "")
            if expected_width and str(expected_width) not in info:
                result["valid"] = False
                result["error"] = f"Width mismatch: expected {expected_width}, got {info}"
            if expected_height and str(expected_height) not in info:
                result["valid"] = False
                result["error"] = f"Height mismatch: expected {expected_height}, got {info}"
        return result
