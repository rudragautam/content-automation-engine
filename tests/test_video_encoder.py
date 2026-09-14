"""Tests for FFmpegEncoder."""
import unittest
import os
import json
import tempfile
import shutil

from rendering.video_encoder import FFmpegEncoder, get_ffmpeg_path


class TestFFmpegAvailability(unittest.TestCase):
    def test_get_ffmpeg_path_found(self):
        path = get_ffmpeg_path()
        self.assertTrue(os.path.isfile(path), f"FFmpeg not at {path}")


class TestFFmpegEncoderInit(unittest.TestCase):
    def test_default_init(self):
        encoder = FFmpegEncoder()
        self.assertIsNotNone(encoder.ffmpeg_path)
        self.assertEqual(encoder.fps, 30)
        self.assertEqual(encoder.output_format, "mp4")

    def test_custom_fps(self):
        encoder = FFmpegEncoder(fps=24)
        self.assertEqual(encoder.fps, 24)

    def test_custom_ffmpeg_path(self):
        encoder = FFmpegEncoder(ffmpeg_path="/usr/bin/ffmpeg")
        self.assertEqual(encoder.ffmpeg_path, "/usr/bin/ffmpeg")


class TestFFmpegEncoderValidate(unittest.TestCase):
    def test_validate_nonexistent(self):
        encoder = FFmpegEncoder()
        result = encoder.validate("/nonexistent/path.mp4")
        self.assertFalse(result["valid"])
        self.assertIn("does not exist", result["error"])

    def test_validate_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp, "empty.mp4")
            open(empty, "wb").close()
            encoder = FFmpegEncoder()
            result = encoder.validate(empty)
            self.assertFalse(result["valid"])
            self.assertIn("empty", result["error"].lower())


class TestFFmpegEncoderEncode(unittest.TestCase):
    def test_encode_generates_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames_dir = os.path.join(tmp, "frames")
            os.makedirs(frames_dir)
            frame_paths = []
            for i in range(3):
                frame_path = os.path.join(frames_dir, f"frame_{i:04d}.png")
                from PIL import Image
                img = Image.new("RGB", (1080, 1920), color=(100 + i * 30, 150, 200))
                img.save(frame_path)
                frame_paths.append(frame_path)

            output_path = os.path.join(tmp, "test.mp4")
            encoder = FFmpegEncoder(fps=1)
            result = encoder.encode_frames(
                frames=frame_paths,
                output_path=output_path,
                width=1080,
                height=1920,
            )
            self.assertTrue(os.path.isfile(result))
            self.assertGreater(os.path.getsize(result), 0)
            metadata = encoder.get_metadata(result)
            self.assertIn("Video:", metadata.get("video_info", ""))

    def test_encode_no_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            encoder = FFmpegEncoder()
            with self.assertRaises(ValueError) as cm:
                encoder.encode_frames([], os.path.join(tmp, "out.mp4"), 1080, 1920)
            self.assertIn("No frames", str(cm.exception))
