"""Hub-level tests for Gemini settings and drafts, with a fake model."""
import json
import unittest
from unittest import mock

from content_templates import get_spec
from content_templates.excel import read_workbook
from providers.ai.gemini import GeminiError
from tests.test_content_ai import FakeClient, model_video
from tests.test_webapp import HubTestCase
from webapp import ai_drafts, db

KEY = "AIzaTESTKEY1234567890abcd"
MODELS = [{"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"}, {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"}]


class FakeGemini:
    def __init__(self, key, model=None):
        if key != KEY:
            raise GeminiError("The Gemini API key isn't valid. Check it in Settings.")

    def list_models(self):
        return MODELS

    def close(self):
        pass


class TestGeminiInHub(HubTestCase):
    def setUp(self):
        super().setUp()
        self.spec = get_spec("focus_habits")
        patcher = mock.patch("webapp.ai_drafts.Gemini", FakeGemini)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save_key(self):
        return self.client.post("/settings/gemini", data={"api_key": KEY})

    def start(self, topic="focus at work", count=2):
        with mock.patch("webapp.ai_drafts.threading.Thread"):
            r = self.client.post("/content/focus_habits/generate",
                                 data={"channel_id": str(self.focus_channel), "topic": topic, "count": str(count), "instructions": ""},
                                 follow_redirects=False)
        return int(r.headers["location"].rsplit("/", 1)[-1]) if r.status_code == 303 and "/drafts/" in r.headers["location"] else r

    def test_key_is_tested_saved_and_masked(self):
        r = self.client.post("/settings/gemini", data={"api_key": "wrong"})
        self.assertIn("isn&#39;t valid", r.text)
        r = self.save_key()
        self.assertIn("2 models available", r.text)
        self.assertNotIn(KEY, r.text)
        self.assertIn("AIza…abcd", r.text)
        with db.session() as conn:
            self.assertEqual(db.get_setting(conn, "gemini_model"), "gemini-2.5-flash")

    def test_model_must_come_from_the_list(self):
        self.save_key()
        self.assertIn("Pick a model from the list", self.client.post("/settings/gemini/model", data={"model": "made-up"}).text)
        self.client.post("/settings/gemini/model", data={"model": "gemini-2.0-flash"})
        with db.session() as conn:
            self.assertEqual(db.get_setting(conn, "gemini_model"), "gemini-2.0-flash")

    def test_generate_needs_a_key(self):
        r = self.start()
        self.assertIn("Add your Gemini API key in Settings first", r.headers["location"].replace("+", " "))

    def test_draft_review_and_queue(self):
        self.save_key()
        with db.session() as conn:
            conn.execute("UPDATE videos SET title = 'Deep Work in 4 Steps' WHERE channel_id = ?", (self.focus_channel,))
        draft_id = self.start(count=2)
        self.assertIn("Writing", self.client.get(f"/drafts/{draft_id}").text)

        good = model_video(self.spec)
        client = FakeClient([{"videos": [good, dict(good, youtube_title="Second")]}])
        ai_drafts.run_draft(draft_id, client=client)
        self.assertIn("Deep Work in 4 Steps", client.prompts[0][0])  # recent titles are passed on

        page = self.client.get(f"/drafts/{draft_id}").text
        self.assertIn("2 of 2 videos pass every check", page)
        self.assertEqual(json.loads(self.client.get(f"/api/drafts/{draft_id}").text)["status"], "ready")

        r = self.client.post(f"/drafts/{draft_id}/queue")
        self.assertIn("Added 2 videos from Gemini", r.text)
        own = self.own_videos()
        self.assertEqual([v["status"] for v in own], ["ready", "ready"])
        self.assertEqual(json.loads(own[0]["content_json"])["intro"]["title"], good["intro"]["title"])
        self.assertIn("isn&#39;t ready to queue", self.client.post(f"/drafts/{draft_id}/queue").text)

    def test_only_valid_videos_are_queued(self):
        self.save_key()
        draft_id = self.start(count=2)
        good = model_video(self.spec)
        broken = dict(good, intro=dict(good["intro"], title=""))
        ai_drafts.run_draft(draft_id, client=FakeClient([{"videos": [good, broken]}, {"videos": [broken]}]))
        page = self.client.get(f"/drafts/{draft_id}").text
        self.assertIn("1 of 2 videos pass every check", page)
        self.assertIn("intro_title: required", page)
        self.client.post(f"/drafts/{draft_id}/queue")
        self.assertEqual(len(self.own_videos()), 1)

    def test_excel_download_round_trips(self):
        self.save_key()
        draft_id = self.start(count=1)
        ai_drafts.run_draft(draft_id, client=FakeClient([{"videos": [model_video(self.spec)]}]))
        r = self.client.get(f"/drafts/{draft_id}/excel")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(read_workbook(r.content, self.spec).ok)

    def test_failed_generation_is_reported(self):
        self.save_key()
        draft_id = self.start(count=1)

        class Broken:
            def generate_json(self, *a, **k):
                raise GeminiError("Gemini's rate limit or quota is used up. Wait a minute and try again.")

        ai_drafts.run_draft(draft_id, client=Broken())
        self.assertIn("rate limit or quota", self.client.get(f"/drafts/{draft_id}").text)

    def test_channel_must_match_niche_and_topic_is_required(self):
        self.save_key()
        with mock.patch("webapp.ai_drafts.threading.Thread"):
            wrong = self.client.post("/content/focus_habits/generate", data={"channel_id": str(self.other_channel), "topic": "x", "count": "1"})
            empty = self.client.post("/content/focus_habits/generate", data={"channel_id": str(self.focus_channel), "topic": " ", "count": "1"})
        self.assertIn("Pick a channel from this niche", wrong.text)
        self.assertIn("Give a topic or theme", empty.text)

    def test_discard_hides_the_draft(self):
        self.save_key()
        draft_id = self.start()
        self.client.post(f"/drafts/{draft_id}/discard")
        self.assertNotIn(f"/drafts/{draft_id}", self.client.get("/content?niche=focus_habits").text)


if __name__ == "__main__":
    unittest.main()
