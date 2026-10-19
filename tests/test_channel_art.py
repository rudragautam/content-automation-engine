"""Gemini banner and watermark drafts: image model, the designed fallback, and saving a draft."""
import base64
import io
import json
import os
import unittest
from unittest import mock

import httpx
from PIL import Image

from providers.ai.gemini import Gemini, GeminiError, GeminiQuotaError, pick_image_model
from tests.test_channel_setup import fake_youtube
from tests.test_webapp import HubTestCase
from webapp import channel_art, db, youtube_sync


def png(size, color=(255, 255, 255), badge=True):
    image = Image.new("RGB", size, color)
    if badge:
        Image.Image.paste(image, (200, 40, 40), (size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


DESIGN = {"tagline": "Khel Khel Mein Seekho!", "icon": "🦁", "background": "#FF8A00", "background_2": "#ffb703",
          "accent": "#2a9d8f", "pattern": "stars", "style": "playful", "subscribe_label": "SUBSCRIBE"}


class TestGeminiImages(unittest.TestCase):
    def test_image_comes_back_as_bytes(self):
        seen = {}

        def handler(request):
            seen.update(path=request.url.path, body=json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"PNGDATA").decode()}}]}}]})

        client = Gemini("key", "text-model", transport=httpx.MockTransport(handler))
        self.assertEqual(client.generate_image("a banner", "16:9", model="gemini-3.1-flash-image"), b"PNGDATA")
        self.assertTrue(seen["path"].endswith("/models/gemini-3.1-flash-image:generateContent"))
        self.assertEqual(seen["body"]["generationConfig"]["imageConfig"], {"aspectRatio": "16:9"})

    def test_zero_quota_is_its_own_error_and_is_not_retried(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429, json={"error": {"message": "Quota exceeded for metric: free_tier_requests, limit: 0, model: x", "status": "RESOURCE_EXHAUSTED"}})

        client = Gemini("key", "m", transport=httpx.MockTransport(handler))
        with self.assertRaises(GeminiQuotaError):
            client.generate_image("x")
        self.assertEqual(len(calls), 1)

    def test_no_image_in_answer(self):
        client = Gemini("key", "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "no"}]}}]})))
        with self.assertRaises(GeminiError):
            client.generate_image("x")

    def test_pick_image_model_prefers_stable_flash(self):
        ids = ["gemini-3-pro-image", "gemini-3.1-flash-image-preview", "gemini-2.5-flash-image", "gemini-3.1-flash-image", "gemini-3.1-flash-lite"]
        self.assertEqual(pick_image_model([{"id": i} for i in ids]), "gemini-3.1-flash-image")
        self.assertIsNone(pick_image_model([{"id": "gemini-3.1-flash-lite"}]))


class TestArtHelpers(unittest.TestCase):
    def test_split_icon(self):
        self.assertEqual(channel_art.split_icon("🦁 Leo Ki Pathshala"), ("🦁", "Leo Ki Pathshala"))
        self.assertEqual(channel_art.split_icon("Crime Files"), ("", "Crime Files"))

    def test_design_is_cleaned(self):
        ctx = {"icon": "", "name": "X"}
        design = channel_art.clean_design({"tagline": "<b>" + "t" * 99, "background": "red", "pattern": "nope", "style": "?"}, ctx)
        self.assertEqual((design["background"], design["pattern"], design["style"], design["subscribe_label"]), ("#1e3a8a", "dots", "bold", "SUBSCRIBE"))
        self.assertNotIn("<", design["tagline"])
        self.assertEqual(len(design["tagline"]), 60)
        self.assertEqual(channel_art.clean_design(DESIGN, {"icon": "🐯", "name": "X"})["icon"], "🐯")  # the channel's own emoji wins
        self.assertEqual(channel_art.clean_design(DESIGN, ctx)["background"], "#ff8a00")
        self.assertEqual(channel_art.clean_design({"accent": "1E88E5"}, ctx)["accent"], "#1e88e5")

    def test_text_colour_contrasts(self):
        self.assertEqual(channel_art.ink_for("#0b1d3a"), "#ffffff")
        self.assertEqual(channel_art.ink_for("#ffd166"), "#111827")

    def test_banner_page_escapes_and_keeps_the_safe_area(self):
        page = channel_art.banner_html({"name": "A <b> & B", "icon": ""}, channel_art.clean_design(DESIGN, {"icon": "", "name": ""}))
        self.assertIn("A &lt;b&gt; &amp; B", page)
        self.assertIn("width:1546px;height:423px", page)

    def test_artwork_is_fitted_to_youtube_sizes(self):
        banner = Image.open(io.BytesIO(channel_art._fit("banner", png((1344, 768)))))
        self.assertEqual((banner.size, banner.format), ((2560, 1440), "JPEG"))
        mark = Image.open(io.BytesIO(channel_art._fit("watermark", png((1024, 1024)))))
        self.assertEqual((mark.size, mark.format), ((512, 512), "PNG"))
        self.assertEqual(mark.getpixel((0, 0))[3], 0)  # white background cleared
        self.assertEqual(mark.getpixel((256, 256))[3], 255)  # the badge kept


class FakeArtClient:
    def __init__(self, image=None, quota=False):
        self.image, self.quota, self.image_calls, self.prompts = image, quota, [], []

    def generate_image(self, prompt, aspect_ratio="1:1", model=None):
        self.image_calls.append((aspect_ratio, model))
        if self.quota:
            raise GeminiQuotaError("no image quota")
        return self.image

    def generate_json(self, prompt, schema, system="", temperature=0.9):
        self.prompts.append(prompt)
        return dict(DESIGN)


class TestArtInHub(HubTestCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            self.ch = youtube_sync.add_channel(conn, "🦁 Leo Ki Pathshala", "focus_habits", "19:00")
            conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = 'UCleo' WHERE id = ?", (self.ch,))
            db.set_setting(conn, "gemini_models", json.dumps([{"id": "gemini-3.1-flash-lite", "name": "x"}, {"id": "gemini-3.1-flash-image", "name": "y"}]))
        self.fake = fake_youtube()
        patcher = mock.patch("webapp.channel_setup._youtube", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def drawn(self, ctx, design, kinds):
        self.design = design
        return {kind: png(channel_art.SIZES[kind]) for kind in kinds}

    def test_painted_by_the_image_model_when_the_key_allows(self):
        client = FakeArtClient(image=png((1344, 768)))
        with db.session() as conn:
            out = channel_art.generate(conn, self.ch, ["banner"], "jungle", client=client)
        self.assertEqual(out["how"], "artwork")
        self.assertEqual(client.image_calls, [("16:9", "gemini-3.1-flash-image")])
        with Image.open(channel_art.draft_path(self.ch, "banner")) as banner:
            self.assertEqual(banner.size, (2560, 1440))
        self.assertIn(f"/channels/{self.ch}/setup/draft/banner", out["drafts"]["banner"])

    def test_free_tier_key_falls_back_to_a_design_and_remembers(self):
        client = FakeArtClient(quota=True)
        with db.session() as conn, mock.patch("webapp.channel_art.render", side_effect=self.drawn):
            out = channel_art.generate(conn, self.ch, ["banner", "watermark"], "", client=client)
            self.assertEqual(out["how"], "design")
            self.assertIn("billing", out["note"])
            self.assertEqual(set(out["drafts"]), {"banner", "watermark"})
            self.assertEqual(self.design["icon"], "🦁")
            self.assertIn("Old about", client.prompts[0])  # the live About text guides the look
            channel_art.generate(conn, self.ch, ["watermark"], "", client=client)
        self.assertEqual(len(client.image_calls), 1)  # not tried again the same day

    def test_page_upload_download_and_discard_a_draft(self):
        with db.session() as conn, mock.patch("webapp.channel_art.render", side_effect=self.drawn):
            channel_art.generate(conn, self.ch, ["banner", "watermark"], "", client=FakeArtClient(quota=True))
        page = self.client.get(f"/channels/{self.ch}/setup").text
        self.assertIn("Upload this banner", page)
        self.assertIn("Set this watermark", page)
        self.assertEqual(page.count("Generate with Gemini"), 1)
        got = self.client.get(f"/channels/{self.ch}/setup/draft/banner?download=1")
        self.assertEqual(got.status_code, 200)
        self.assertIn("attachment", got.headers["content-disposition"])

        r = self.client.post(f"/channels/{self.ch}/setup/banner", data={"draft": "1"})
        self.assertIn("Banner uploaded", r.text)
        self.assertEqual(len([c for c in self.fake.calls if c[:2] == ("channelBanners", "insert")]), 1)
        self.assertFalse(os.path.exists(channel_art.draft_path(self.ch, "banner")))
        self.assertIn("no Gemini banner yet", self.client.post(f"/channels/{self.ch}/setup/banner", data={"draft": "1"}).text)

        r = self.client.post(f"/channels/{self.ch}/setup/watermark", data={"draft": "1", "timing": "end"})
        self.assertIn("Watermark set", r.text)
        self.client.post(f"/channels/{self.ch}/setup/draft/watermark/discard")
        self.assertEqual(self.client.get(f"/channels/{self.ch}/setup/draft/watermark").status_code, 404)

    def test_generate_art_route_needs_a_key(self):
        self.assertIn("Gemini API key", self.client.post(f"/api/channels/{self.ch}/setup/generate-art", data={"kinds": "banner"}).json()["error"])
        self.assertIn("Pick the banner", self.client.post(f"/api/channels/{self.ch}/setup/generate-art", data={"kinds": "logo"}).json()["error"])

    def test_planned_channel_can_make_and_download_art(self):
        with db.session() as conn:
            planned = youtube_sync.add_channel(conn, "Planned", "crime_files", "19:00")
        page = self.client.get(f"/channels/{planned}/setup").text
        self.assertIn("Generate banner", page)
        self.assertNotIn("Upload this banner", page)
        self.assertIn("download them for YouTube Studio", page)


class TestRealRender(unittest.TestCase):
    def test_render_draws_both_at_youtube_sizes(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                p.chromium.launch().close()
        except Exception:
            self.skipTest("Chromium isn't installed")
        ctx = {"name": "Leo Ki Pathshala", "icon": "🦁"}
        out = channel_art.render(ctx, channel_art.clean_design(DESIGN, ctx), ["banner", "watermark"])
        banner, mark = Image.open(io.BytesIO(out["banner"])), Image.open(io.BytesIO(out["watermark"]))
        self.assertEqual((banner.size, banner.format), ((2560, 1440), "JPEG"))
        self.assertEqual((mark.size, mark.format), ((512, 512), "PNG"))
        self.assertEqual(mark.convert("RGBA").getpixel((0, 0))[3], 0)  # transparent outside the badge


if __name__ == "__main__":
    unittest.main()
