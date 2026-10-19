"""Channel setup: the YouTube calls, the hub's validation, and upload defaults."""
import io
import json
import unittest
from unittest import mock

from PIL import Image

from publishing import youtube as yt
from tests.test_webapp import HubTestCase
from tests.test_youtube import FakeRequest, FakeService
from webapp import channel_setup, db, youtube_sync

BRANDING = {
    "channel": {"title": "Leo Ki Pathshala", "description": "Old about", "keywords": 'study "focus tips"', "country": "IN"},
    "image": {"bannerExternalUrl": "https://yt3.example/old-banner"},
}


def channel_list():
    return FakeRequest({"items": [{
        "id": "UCleo", "snippet": {"title": "Leo Ki Pathshala", "customUrl": "@leo", "thumbnails": {"default": {"url": "https://yt3.example/pic"}}},
        "brandingSettings": BRANDING, "contentDetails": {"relatedPlaylists": {"uploads": "UUleo"}}, "status": {"madeForKids": False},
    }]})


def fake_youtube(**extra):
    responses = {
        ("channels", "list"): channel_list(),
        ("channels", "update"): FakeRequest({}),
        ("playlists", "list"): FakeRequest({"items": [{"id": "PL1", "snippet": {"title": "Focus Series"}, "status": {"privacyStatus": "public"}, "contentDetails": {"itemCount": 4}}]}),
        ("playlists", "insert"): FakeRequest({"id": "PLnew"}),
        ("playlistItems", "list"): FakeRequest({"items": [{"contentDetails": {"videoId": "abcdefghijk"}}]}),
        ("playlistItems", "insert"): FakeRequest({}),
        ("videos", "list"): FakeRequest({"items": [{"id": "abcdefghijk", "snippet": {"title": "Best video"}, "status": {"privacyStatus": "public"}, "statistics": {}, "contentDetails": {"duration": "PT30S"}}]}),
        ("channelBanners", "insert"): FakeRequest({"url": "https://yt3.example/new-banner"}),
        ("watermarks", "set"): FakeRequest({}),
        ("watermarks", "unset"): FakeRequest({}),
    }
    responses.update(extra)
    return FakeService(responses)


def image_bytes(size, fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 90, 200)).save(buf, fmt)
    return buf.getvalue()


class TestYouTubeCalls(unittest.TestCase):
    def test_keywords_round_trip(self):
        self.assertEqual(yt.format_keywords(["ai", "deep learning", ' "x" ', ""]), 'ai "deep learning" x')
        self.assertEqual(yt.parse_keywords('ai "deep learning" x'), ["ai", "deep learning", "x"])

    def test_branding_update_keeps_other_fields_and_never_sends_the_title(self):
        fake = fake_youtube()
        yt.update_branding(fake, "UCleo", BRANDING, channel={"description": "New", "country": ""})
        body = fake.calls[-1][2]["body"]
        self.assertEqual(body["id"], "UCleo")
        self.assertNotIn("title", body["brandingSettings"]["channel"])
        self.assertEqual(body["brandingSettings"]["channel"]["description"], "New")
        self.assertNotIn("country", body["brandingSettings"]["channel"])  # cleared
        self.assertEqual(body["brandingSettings"]["channel"]["keywords"], 'study "focus tips"')
        self.assertEqual(body["brandingSettings"]["image"]["bannerExternalUrl"], "https://yt3.example/old-banner")
        self.assertEqual(BRANDING["channel"]["title"], "Leo Ki Pathshala")  # input not mutated

    def test_channel_setup_reads_everything(self):
        live = yt.channel_setup(fake_youtube())
        self.assertEqual((live["id"], live["handle"], live["description"], live["keywords"], live["banner"]),
                         ("UCleo", "@leo", "Old about", ["study", "focus tips"], "https://yt3.example/old-banner"))


class TestSetupInHub(HubTestCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            self.ch = youtube_sync.add_channel(conn, "Leo Ki Pathshala", "focus_habits", "19:00")
            conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = 'UCleo' WHERE id = ?", (self.ch,))
        self.fake = fake_youtube()
        patcher = mock.patch("webapp.channel_setup._youtube", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def calls(self, resource, method):
        return [c[2] for c in self.fake.calls if c[:2] == (resource, method)]

    def test_page_shows_what_is_live_on_youtube(self):
        page = self.client.get(f"/channels/{self.ch}/setup").text
        for text in ("Channel setup", "Old about", "study, focus tips", "Focus Series", "Best video", "old-banner", "Change in Studio"):
            self.assertIn(text, page)
        self.assertNotIn('class="sidebar"', page)  # its own window, without the hub's sidebar

    def test_channel_page_opens_setup_in_a_window(self):
        page = self.client.get(f"/channels/{self.ch}").text
        self.assertIn(f'href="/channels/{self.ch}/setup" target="setup-{self.ch}" data-setup-window', page)

    def test_save_about(self):
        r = self.client.post(f"/channels/{self.ch}/setup/about", data={"description": "Daily study tips.", "keywords": "study tips, focus,  exam prep", "country": "IN", "language": "hi"})
        self.assertIn("About section saved", r.text)
        info = self.calls("channels", "update")[0]["body"]["brandingSettings"]["channel"]
        self.assertEqual((info["description"], info["keywords"], info["defaultLanguage"]), ("Daily study tips.", '"study tips" focus "exam prep"', "hi"))

    def test_about_validation(self):
        self.assertIn("YouTube allows 1000", self.client.post(f"/channels/{self.ch}/setup/about", data={"description": "x" * 1001}).text)
        self.assertIn("doesn&#39;t allow &lt; or &gt;", self.client.post(f"/channels/{self.ch}/setup/about", data={"description": "<b>hi</b>"}).text)
        self.assertIn("Pick a country", self.client.post(f"/channels/{self.ch}/setup/about", data={"description": "ok", "country": "ZZ"}).text)
        self.assertEqual(self.calls("channels", "update"), [])

    def test_banner_checks_size_then_uploads_and_sets_it(self):
        small = self.client.post(f"/channels/{self.ch}/setup/banner", files={"file": ("b.png", image_bytes((1000, 562)), "image/png")})
        self.assertIn("at least 2048×1152", small.text)
        square = self.client.post(f"/channels/{self.ch}/setup/banner", files={"file": ("b.png", image_bytes((2400, 2400)), "image/png")})
        self.assertIn("16:9 shape", square.text)
        self.assertIn("isn&#39;t an image", self.client.post(f"/channels/{self.ch}/setup/banner", files={"file": ("b.png", b"nope", "image/png")}).text)
        ok = self.client.post(f"/channels/{self.ch}/setup/banner", files={"file": ("b.jpg", image_bytes((2560, 1440), "JPEG"), "image/jpeg")})
        self.assertIn("Banner uploaded", ok.text)
        self.assertEqual(len(self.calls("channelBanners", "insert")), 1)
        image = self.calls("channels", "update")[0]["body"]["brandingSettings"]["image"]
        self.assertEqual(image["bannerExternalUrl"], "https://yt3.example/new-banner")

    def test_watermark_set_and_remove(self):
        self.assertIn("at least 150×150", self.client.post(f"/channels/{self.ch}/setup/watermark", files={"file": ("w.png", image_bytes((64, 64)), "image/png")}).text)
        r = self.client.post(f"/channels/{self.ch}/setup/watermark", data={"timing": "start"}, files={"file": ("w.png", image_bytes((300, 300)), "image/png")})
        self.assertIn("Watermark set", r.text)
        call = self.calls("watermarks", "set")[0]
        self.assertEqual((call["channelId"], call["body"]["timing"]), ("UCleo", {"type": "offsetFromStart", "offsetMs": 0, "durationMs": 0}))
        self.assertIn("Watermark removed", self.client.post(f"/channels/{self.ch}/setup/watermark/remove").text)
        self.assertEqual(self.calls("watermarks", "unset")[0]["channelId"], "UCleo")

    def test_trailer(self):
        self.assertIn("Pick a video", self.client.post(f"/channels/{self.ch}/setup/trailer", data={"video_id": "bad id"}).text)
        self.client.post(f"/channels/{self.ch}/setup/trailer", data={"video_id": "abcdefghijk"})
        self.assertEqual(self.calls("channels", "update")[0]["body"]["brandingSettings"]["channel"]["unsubscribedTrailer"], "abcdefghijk")

    def test_playlist_created_and_used_for_uploads(self):
        r = self.client.post(f"/channels/{self.ch}/setup/playlist", data={"title": "Exam Week", "privacy": "public", "use_for_uploads": "yes"})
        self.assertIn("Exam Week", r.text)
        self.assertEqual(self.calls("playlists", "insert")[0]["body"]["snippet"]["title"], "Exam Week")
        with db.session() as conn:
            self.assertEqual(channel_setup.defaults(conn, self.ch)["playlist_id"], "PLnew")
        self.client.post(f"/channels/{self.ch}/setup/upload-playlist", data={"playlist_id": ""})
        with db.session() as conn:
            self.assertEqual(channel_setup.defaults(conn, self.ch)["playlist_id"], "")

    def test_upload_uses_the_channel_defaults_and_playlist(self):
        r = self.client.post(f"/channels/{self.ch}/setup/defaults", data={
            "category_id": "22", "language": "hi", "made_for_kids": "no", "synthetic_media": "yes",
            "default_tags": "leo, Focus", "description_footer": "Subscribe for daily tips."})
        self.assertIn("Upload defaults saved", r.text)
        with db.session() as conn:
            channel_setup.set_upload_playlist(conn, self.ch, "PL1")
        path = f"{self.tmp}/final.mp4"
        with open(path, "wb") as f:
            f.write(b"x" * 2048)
        with db.session() as conn:
            vid = conn.execute("INSERT INTO videos (channel_id, video_ref, title, description, tags, status, publish_at, video_path, created_at) "
                               "VALUES (?, 'R', 'A video', 'Body', 'focus, habits', 'rendered', '2031-05-04T19:00', ?, 'now')", (self.ch, path)).lastrowid
        upload = FakeService({("videos", "insert"): FakeRequest(chunks=[(None, {"id": "yt123"})]), ("playlistItems", "insert"): FakeRequest({})})
        youtube_sync.upload_now(vid, services=(upload, None))
        body = upload.calls[0][2]["body"]
        self.assertEqual((body["snippet"]["categoryId"], body["snippet"]["defaultLanguage"]), ("22", "hi"))
        self.assertEqual(body["snippet"]["tags"], ["focus", "habits", "leo"])  # "Focus" already there
        self.assertTrue(body["snippet"]["description"].endswith("Subscribe for daily tips."))
        self.assertEqual(upload.calls[1][2]["body"]["snippet"], {"playlistId": "PL1", "resourceId": {"kind": "youtube#video", "videoId": "yt123"}})

    def test_defaults_validation(self):
        self.assertIn("Pick a category", self.client.post(f"/channels/{self.ch}/setup/defaults", data={"category_id": "999", "language": "en"}).text)

    def test_generate_with_gemini_fills_every_section(self):
        with db.session() as conn:
            conn.execute("INSERT INTO videos (channel_id, video_ref, title, status, publish_at, views, youtube_video_id, created_at) "
                         "VALUES (?, 'y1', 'Brush your teeth with Leo', 'published', '2026-09-01T10:00', 900, 'abcdefghijk', 'now')", (self.ch,))

        class Fake:
            def generate_json(self, prompt, schema, system="", temperature=0.9):
                self.prompt, self.schema = prompt, schema
                return {
                    "about": {"description": "Learn <fast> every day.", "keywords": ["kids", "good habits"], "country": "IN", "language": "hi"},
                    "playlist": {"title": "Good Habits", "description": "Daily habits for kids."},
                    "upload_defaults": {"category_id": "27", "language": "hi", "made_for_kids": True,
                                        "default_tags": ["leo ki pathshala", "kids"], "description_footer": "Subscribe! #kids"},
                    "trailer_video_id": "abcdefghijk",
                }

        fake = Fake()
        with db.session() as conn:
            draft = channel_setup.generate_setup(conn, self.ch, client=fake)
        self.assertEqual(draft["about"], {"description": "Learn fast every day.", "keywords": ["kids", "good habits"], "country": "IN", "language": "hi"})
        self.assertEqual(draft["trailer_video_id"], "abcdefghijk")
        self.assertEqual(draft["playlist"]["title"], "Good Habits")
        self.assertEqual(draft["upload_defaults"]["made_for_kids"], True)
        self.assertEqual(draft["upload_defaults"]["synthetic_media"], True)
        self.assertIn("Brush your teeth with Leo", fake.prompt)
        self.assertIn("Old about", fake.prompt)  # the channel's real About text guides Gemini
        self.assertLess(fake.prompt.index("Old about"), fake.prompt.index("HINT ONLY"))
        self.assertEqual(fake.schema["properties"]["trailer_video_id"]["enum"], ["abcdefghijk"])
        with db.session() as conn:  # nothing was saved
            self.assertEqual(channel_setup.defaults(conn, self.ch)["made_for_kids"], False)
        self.assertEqual(self.calls("channels", "update"), [])

    def test_generated_values_outside_the_choices_are_dropped(self):
        draft = channel_setup._clean_setup({
            "about": {"description": "x" * 2000, "keywords": ["k%d" % i for i in range(200)], "country": "ZZ", "language": "xx"},
            "upload_defaults": {"category_id": "999", "language": "hi"},
            "trailer_video_id": "notalistedid",
        }, {"abcdefghijk"})
        self.assertEqual(len(draft["about"]["description"]), 1000)
        self.assertLessEqual(len(yt.format_keywords(draft["about"]["keywords"])), 500)
        self.assertEqual((draft["about"]["country"], draft["about"]["language"], draft["upload_defaults"]["category_id"], draft["trailer_video_id"]), ("", "", "", ""))

    def test_generate_needs_a_key_and_page_has_one_button(self):
        self.assertIn("Gemini API key", self.client.post(f"/api/channels/{self.ch}/setup/generate").json()["error"])
        page = self.client.get(f"/channels/{self.ch}/setup").text
        self.assertEqual(page.count("Generate with Gemini"), 1)
        for field in ("about-description", "about-keywords", "about-country", "trailer-video", "playlist-title", "defaults-category", "defaults-footer"):
            self.assertIn(f'id="{field}"', page)

    def test_not_connected_channel_explains_what_to_do(self):
        with db.session() as conn:
            planned = youtube_sync.add_channel(conn, "Planned", "crime_files", "19:00")
        page = self.client.get(f"/channels/{planned}/setup").text
        self.assertIn("Connect a YouTube channel", page)
        self.assertIn("Upload defaults", page)
        self.assertNotIn('id="about"', page)


if __name__ == "__main__":
    unittest.main()
