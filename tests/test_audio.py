"""Tests for mixing background audio into rendered videos."""
import os
import random
import shutil
import subprocess
import tempfile
import unittest

from rendering.audio import add_background_audio, media_duration, pick_track
from rendering.video_encoder import get_ffmpeg_path


class TestPickTrack(unittest.TestCase):
    def test_avoids_last_track_when_it_can(self):
        rng = random.Random(1)
        self.assertTrue(all(pick_track(["a", "b"], avoid="a", rng=rng) == "b" for _ in range(20)))
        self.assertEqual(pick_track(["a"], avoid="a"), "a")
        self.assertIsNone(pick_track([]))


class TestAddBackgroundAudio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        ffmpeg = get_ffmpeg_path()
        self.video = os.path.join(self.tmp, "v.mp4")
        self.tone = os.path.join(self.tmp, "t.mp3")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x568:d=3:r=30",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", self.video], check=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", self.tone], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_short_track_loops_to_the_video_length(self):
        out = add_background_audio(self.video, self.tone, os.path.join(self.tmp, "out.mp4"))
        self.assertAlmostEqual(media_duration(out), 3.0, delta=0.1)
        probe = subprocess.run([get_ffmpeg_path(), "-hide_banner", "-i", out], capture_output=True, text=True).stderr
        self.assertIn("Audio: aac", probe)
        self.assertIn("stereo", probe)
        self.assertIn("320x568", probe)

    def test_non_media_file_has_no_duration(self):
        path = os.path.join(self.tmp, "x.mp3")
        with open(path, "wb") as f:
            f.write(b"not audio")
        self.assertIsNone(media_duration(path))


if __name__ == "__main__":
    unittest.main()
