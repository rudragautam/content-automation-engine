"""AI Optimizer in the hub: YouTube's limits, before/after, approval, backup and Undo for drafts and queued videos."""
import json
import unittest
from unittest import mock

from content_templates.ai import to_row
from publishing import youtube as yt
from tests.test_content_ai import model_video
from tests.test_optimizer import FakeModel, answer
from tests.test_webapp import HubTestCase
from webapp import channel_setup, db, metadata_apply, optimizer, timeutil


class TestLimits(unittest.TestCase):
    def test_tags_are_counted_like_youtube(self):
        self.assertEqual(yt.tags_length(["a", "b c"]), 1 + 5 + 1)
        self.assertEqual(yt.tags_length([]), 0)
        self.assertEqual(yt.fit_tags(["x" * 300, "y" * 300, "z"]), ["x" * 300, "z"])

    def test_description_limit_is_bytes(self):
        hindi = "क" * 2000  # 6,000 bytes
        self.assertEqual(yt.description_bytes(hindi), 6000)
        cut = yt.fit_description(hindi)
        self.assertLessEqual(yt.description_bytes(cut), yt.DESCRIPTION_LIMIT)
        self.assertEqual(cut, "क" * 1666)  # never half a letter
        body = yt.upload_body("t", hindi, [], None)
        self.assertLessEqual(yt.description_bytes(body["snippet"]["description"]), yt.DESCRIPTION_LIMIT)

    def test_upload_metadata_adds_footer_and_default_tags(self):
        prefs = {"description_footer": "Subscribe!", "default_tags": ["leo", "Kids"]}
        meta = metadata_apply.upload_metadata(prefs, "  Title  ", "Line", ["kids", "habits"])
        self.assertEqual(meta["description"], "Line\n\nSubscribe!")
        self.assertEqual(meta["tags"], ["kids", "habits", "leo"])
        self.assertEqual(meta["title"], "Title")

    def test_limit_problems(self):
        ok = {"title": "a", "description": "b", "tags": ["c"]}
        self.assertEqual(metadata_apply.limit_problems(ok), [])
        bad = {"title": "a" * 101, "description": "क" * 1700, "tags": ["t" * 501]}
        problems = " ".join(metadata_apply.limit_problems(bad))
        self.assertIn("101 characters", problems)
        self.assertIn("5,100 bytes", problems)
        self.assertIn("501 characters", problems)
        self.assertIn("The title is empty.", metadata_apply.limit_problems(dict(ok, title="")))

    def test_parse_tags(self):
        self.assertEqual(metadata_apply.parse_tags("a, b,\nA, , c"), ["a", "b", "c"])


class TestSuggestionsInHub(HubTestCase):
    def setUp(self):
        super().setUp()
        self.ai = mock.patch("webapp.ai_drafts.api_key", return_value="AIzaTESTKEY")
        self.ai.start()
        self.addCleanup(self.ai.stop)
        self.thread = mock.patch("webapp.optimizer.threading.Thread")
        self.thread.start()
        self.addCleanup(self.thread.stop)
        with db.session() as conn:
            db.set_setting(conn, "gemini_model", "gemini-test-flash-lite")
            channel_setup._store(conn, self.focus_channel, dict(channel_setup.defaults(conn, self.focus_channel),
                                                                language="hi", made_for_kids=True, description_footer="Subscribe karo!", default_tags=["focus daily"]))
            rows = [to_row(self.spec, model_video(self.spec)), to_row(self.spec, model_video(self.spec, youtube_title="Second"))]
            self.draft = conn.execute(
                "INSERT INTO drafts (niche, channel_id, topic, count, model, status, rows_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                ("focus_habits", self.focus_channel, "haath dhona", 2, "gemini-test-flash-lite", "ready", json.dumps(rows), timeutil.fmt(timeutil.now_local()))).lastrowid

    def run_suggestions(self, replies, live_kids=None):
        with db.session() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM video_suggestions WHERE status = 'generating' ORDER BY id")]
        model = FakeModel(replies)
        optimizer.run(ids, client=model, live_kids=lambda conn, cid: live_kids)
        return model

    def suggestion(self, sid=None):
        with db.session() as conn:
            q = "SELECT * FROM video_suggestions " + ("WHERE id = ?" if sid else "ORDER BY id DESC LIMIT 1")
            return dict(conn.execute(q, (sid,) if sid else ()).fetchone())

    def draft_row(self, n=1):
        with db.session() as conn:
            return json.loads(conn.execute("SELECT rows_json FROM drafts WHERE id = ?", (self.draft,)).fetchone()[0])[n - 1]

    def apply(self, sid, **form):
        data = {"title": "हाथ धोना क्यों ज़रूरी है?", "description": "नई जानकारी", "tags": "haath dhona, good habits", "approve": "yes"}
        data.update(form)
        return self.client.post(f"/suggestions/{sid}/apply", data=data, follow_redirects=False)

    def test_draft_row_suggest_review_apply_undo(self):
        r = self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("Gemini is writing", self.client.get(f"/drafts/{self.draft}").text)
        model = self.run_suggestions([answer()])
        prompt = model.prompts[0][0]
        self.assertIn("Never ask viewers to comment", prompt)  # the channel's own Made for Kids default
        self.assertIn("Subscribe karo!", prompt)

        s = self.suggestion()
        self.assertEqual(s["status"], "ready")
        page = self.client.get(f"/drafts/{self.draft}").text
        self.assertIn("हाथ धोना क्यों ज़रूरी है? | Good Habits for Kids", page)
        self.assertIn("Before", page)
        self.assertIn("I've read the before and after", page)
        self.assertIn("For the video itself", page)

        original = self.draft_row()
        r = self.apply(s["id"])
        self.assertIn("Applied+the+new", r.headers["location"])
        row = self.draft_row()
        self.assertEqual(row["youtube_title"], "हाथ धोना क्यों ज़रूरी है?")
        self.assertEqual(row["youtube_tags"], "haath dhona, good habits")
        self.assertEqual(row["intro_title"], original["intro_title"])  # only metadata changes
        self.assertEqual(json.loads(self.suggestion(s["id"])["before_json"])["title"], original["youtube_title"])

        r = self.client.post(f"/suggestions/{s['id']}/undo", follow_redirects=False)
        self.assertIn("Undone", r.headers["location"])
        self.assertEqual(self.draft_row()["youtube_title"], original["youtube_title"])
        self.assertEqual(self.suggestion(s["id"])["status"], "ready")

    def test_apply_needs_approval_and_respects_limits(self):
        self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"})
        self.run_suggestions([answer()])
        sid = self.suggestion()["id"]
        before = self.draft_row()["youtube_title"]
        self.assertIn("approve", self.apply(sid, approve="").headers["location"])
        self.assertIn("101+characters", self.apply(sid, title="a" * 101).headers["location"])
        self.assertIn("bytes", self.apply(sid, description="क" * 1700).headers["location"])
        self.assertIn("Nothing+changed", self.apply(sid, title=before, description=self.draft_row()["youtube_description"],
                                                    tags=self.draft_row()["youtube_tags"]).headers["location"])
        self.assertEqual(self.draft_row()["youtube_title"], before)

    def test_apply_twice_keeps_the_original_backup(self):
        self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"})
        self.run_suggestions([answer()])
        sid = self.suggestion()["id"]
        original = self.draft_row()["youtube_title"]
        self.apply(sid)
        self.apply(sid, title="दूसरा शीर्षक")
        self.client.post(f"/suggestions/{sid}/undo")
        self.assertEqual(self.draft_row()["youtube_title"], original)

    def test_undo_refuses_after_a_later_edit(self):
        self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"})
        self.run_suggestions([answer()])
        sid = self.suggestion()["id"]
        self.apply(sid)
        with db.session() as conn:
            rows = json.loads(conn.execute("SELECT rows_json FROM drafts WHERE id = ?", (self.draft,)).fetchone()[0])
            rows[0]["youtube_title"] = "Edited by hand"
            conn.execute("UPDATE drafts SET rows_json = ? WHERE id = ?", (json.dumps(rows), self.draft))
        r = self.client.post(f"/suggestions/{sid}/undo", follow_redirects=False)
        self.assertIn("changed+again", r.headers["location"])
        self.assertEqual(self.draft_row()["youtube_title"], "Edited by hand")

    def test_queued_draft_is_no_longer_changed_here(self):
        self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"})
        self.run_suggestions([answer()])
        with db.session() as conn:
            conn.execute("UPDATE drafts SET status = 'queued' WHERE id = ?", (self.draft,))
        r = self.apply(self.suggestion()["id"])
        self.assertIn("already+added+to+the+queue", r.headers["location"])
        r = self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"}, follow_redirects=False)
        self.assertIn("problem=Only+a+draft", r.headers["location"])

    def test_all_rows_one_request_each_and_failures_are_readable(self):
        self.client.post(f"/drafts/{self.draft}/suggest")
        model = self.run_suggestions([answer(), answer(titles=["x", "y", "z"]), answer(titles=["x", "y", "z"])])
        self.assertEqual(len(model.prompts), 3)  # row 2 was retried once
        with db.session() as conn:
            rows = {r["draft_row"]: dict(r) for r in conn.execute("SELECT * FROM video_suggestions WHERE draft_id = ?", (self.draft,))}
        self.assertEqual(rows[1]["status"], "ready")
        self.assertEqual(rows[2]["status"], "failed")
        self.assertIn("keeps its current title", rows[2]["error"])
        self.assertIn("Try again", self.client.get(f"/drafts/{self.draft}").text)

    def test_live_made_for_kids_wins_and_warns(self):
        with db.session() as conn:
            channel_setup._store(conn, self.focus_channel, dict(channel_setup.defaults(conn, self.focus_channel), made_for_kids=False))
        self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"})
        model = self.run_suggestions([answer()], live_kids=True)
        self.assertIn("Never ask viewers to comment", model.prompts[0][0])
        s = self.suggestion()
        self.assertEqual(s["made_for_kids"], 1)
        self.assertIn("upload defaults in the hub say No", s["warnings_json"])
        with db.session() as conn:  # neither setting is changed
            self.assertFalse(channel_setup.defaults(conn, self.focus_channel)["made_for_kids"])

    def test_queued_video_suggestions_page(self):
        with db.session() as conn:
            vid = conn.execute(
                "INSERT INTO videos (channel_id, video_ref, title, description, tags, status, publish_at, duration_s, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (self.focus_channel, "LEO-1", "Old title", "Old description", "old", "rendered", "2099-01-01T09:00", 12.0, timeutil.fmt(timeutil.now_local()))).lastrowid
        self.assertIn("Suggest with Gemini", self.client.get(f"/videos/{vid}/suggestions").text)
        self.assertIn(f"/videos/{vid}/suggestions", self.client.get(f"/channels/{self.focus_channel}").text)
        self.client.post(f"/videos/{vid}/suggest")
        self.run_suggestions([answer()])
        sid = self.suggestion()["id"]
        r = self.apply(sid)
        self.assertIn(f"/videos/{vid}/suggestions?notice=", r.headers["location"])
        with db.session() as conn:
            v = conn.execute("SELECT title, tags FROM videos WHERE id = ?", (vid,)).fetchone()
            self.assertEqual((v["title"], v["tags"]), ("हाथ धोना क्यों ज़रूरी है?", "haath dhona, good habits"))
            conn.execute("UPDATE videos SET status = 'scheduled', youtube_video_id = 'yt123' WHERE id = ?", (vid,))
        r = self.client.post(f"/suggestions/{sid}/undo", follow_redirects=False)
        self.assertIn("already+on+YouTube", r.headers["location"])
        self.assertIn("already+on+YouTube", self.client.post(f"/videos/{vid}/suggest", follow_redirects=False).headers["location"])

    def test_upload_sends_what_the_preview_checked(self):
        with db.session() as conn:
            prefs = channel_setup.defaults(conn, self.focus_channel)
        captured = {}
        meta = metadata_apply.upload_metadata(prefs, "शीर्षक", "विवरण", ["a"])
        with mock.patch("publishing.youtube.upload_body", side_effect=lambda *a, **k: captured.update(args=a) or {}), \
             mock.patch("publishing.youtube.upload_video", side_effect=yt.YouTubeError("stop here")):
            with db.session() as conn:
                vid = conn.execute(
                    "INSERT INTO videos (channel_id, video_ref, title, description, tags, status, video_path, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (self.focus_channel, "LEO-2", "शीर्षक", "विवरण", "a", "rendered", "x.mp4", timeutil.fmt(timeutil.now_local()))).lastrowid
            from webapp import youtube_sync
            youtube_sync.upload_now(vid, services=(None, None))
        self.assertEqual(captured["args"][:3], (meta["title"], meta["description"], meta["tags"]))

    def test_needs_a_gemini_key(self):
        with mock.patch("webapp.ai_drafts.api_key", return_value=None):
            r = self.client.post(f"/drafts/{self.draft}/suggest", data={"row": "1"}, follow_redirects=False)
        self.assertIn("Gemini+API+key", r.headers["location"])


if __name__ == "__main__":
    unittest.main()
