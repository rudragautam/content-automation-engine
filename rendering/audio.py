"""Background audio for rendered videos.

The track is looped if it is shorter than the video, cut at the video's
end with a short fade-out, and loudness-normalised to about -14 LUFS, the
level YouTube plays back at. The video stream is copied untouched.
"""

import logging
import os
import random
import re
import subprocess
from typing import Optional, Sequence

from rendering.video_encoder import get_ffmpeg_path

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
FADE_OUT_SECONDS = 1.0


def media_duration(path: str) -> Optional[float]:
    """Duration in seconds read from ffmpeg's probe output, or None if it has no audio or video."""
    result = subprocess.run([get_ffmpeg_path(), "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace")
    if "Audio:" not in result.stderr and "Video:" not in result.stderr:
        return None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def pick_track(tracks: Sequence[str], avoid: Optional[str] = None, rng: random.Random = None) -> Optional[str]:
    """A random track, never the one used last unless it is the only one."""
    choices = [t for t in tracks if t != avoid] or list(tracks)
    return (rng or random).choice(choices) if choices else None


def add_background_audio(video_path: str, audio_path: str, out_path: str) -> str:
    duration = media_duration(video_path)
    if not duration:
        raise ValueError(f"cannot read the length of {video_path}")
    fade_start = max(0.0, duration - FADE_OUT_SECONDS)
    cmd = [
        get_ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-stream_loop", "-1", "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-af", f"loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={fade_start:.2f}:d={FADE_OUT_SECONDS}",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to add audio: {result.stderr.strip()[-500:]}")
    logger.info("Added %s to %s", os.path.basename(audio_path), out_path)
    return out_path
