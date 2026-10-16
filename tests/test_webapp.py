"""Tests for the content hub web app, against a temporary database."""
import io
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from content_templates import build_workbook, get_spec
from webapp import db, mock, queue, timeutil

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sheet(spec, rows):
    wb = build_workbook(spec)
    names = [name for name, _, _ in spec.columns()]
    for r, row in enumerate(rows, start=2):
        for key, value in row.items():
            wb["Content"].cell(row=r, column=names.index(key) + 1, value=value)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class HubTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._hub_dir = db.HUB_DIR
        db.HUB_DIR = self.tmp
        from webapp.app import app
        self.client = TestClient(app)
        self.client.__enter__()  # runs startup: schema + mock seed
        self.spec = get_spec("focus_habits")
        with db.session() as conn:
            self.focus_channel = conn.execute("SELECT id FROM channels WHERE name = 'Focus Daily'").fetchone()[0]
            self.other_channel = conn.execute("SELECT id FROM channels WHERE niche != 'focus_habits' LIMIT 1").fetchone()[0]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        db.HUB_DIR = self._hub_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def upload(self, rows, channel_id=None, niche="focus_habits"):
        return self.client.post(
            f"/content/{niche}/upload", data={"channel_id": str(channel_id or self.focus_channel)},
            files={"file": ("sheet.xlsx", sheet(get_spec(niche), rows), XLSX)})

    def own_videos(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM videos WHERE is_mock = 0 ORDER BY id")]


class TestPages(HubTestCase):
    def test_every_page_renders(self):
        for url in ["/", "/?days=7", "/?days=90", "/channels/1", "/schedule", "/schedule?channel=2",
                    "/content", "/content?niche=crime_files", "/audio", "/analytics?days=90"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_mock_banner_and_seed_runs_once(self):
        self.assertIn("Mock data.", self.client.get("/").text)
        with db.session() as conn:
            before = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            mock.seed(conn)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0], before)
        self.assertEqual(before, 20)

    def test_template_download(self):
        r = self.client.get("/content/geeta_gyaan/template.xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("geeta_gyaan_content_template.xlsx", r.headers["content-disposition"])
        self.assertEqual(self.client.get("/content/nope/template.xlsx").status_code, 404)


class TestContentUpload(HubTestCase):
    def test_bad_sheet_adds_nothing_and_lists_errors(self):
        r = self.upload([dict(self.spec.example, intro_title="")])
        self.assertIn("intro_title", r.text)
        self.assertIn("Nothing was added", r.text)
        self.assertEqual(self.own_videos(), [])

    def test_good_sheet_fills_next_free_slots(self):
        second = dict(self.spec.example, video_id="FH-002")
        self.assertIn("2 videos queued", self.upload([self.spec.example, second]).text)
        videos = self.own_videos()
        self.assertEqual([v["status"] for v in videos], ["ready", "ready"])
        with db.session() as conn:
            taken = [r[0] for r in conn.execute(
                "SELECT publish_at FROM videos WHERE channel_id = ? AND status IN ('ready','scheduled')", (self.focus_channel,))]
        self.assertEqual(len(taken), len(set(taken)), "two videos share a slot")

    def test_publish_time_from_sheet_is_kept(self):
        self.upload([dict(self.spec.example, publish_at="2031-05-04 18:30")])
        self.assertEqual(self.own_videos()[0]["publish_at"], "2031-05-04T18:30")

    def test_past_publish_time_and_duplicates_are_refused(self):
        self.assertIn("is in the past", self.upload([dict(self.spec.example, publish_at="2020-01-01 10:00")]).text)
        self.upload([self.spec.example])
        self.assertIn("already in this channel", self.upload([self.spec.example]).text)
        self.assertEqual(len(self.own_videos()), 1)

    def test_channel_must_belong_to_the_niche(self):
        self.assertIn("Pick a channel from this niche", self.upload([self.spec.example], channel_id=self.other_channel).text)


class TestScheduling(HubTestCase):
    def test_reschedule_rules(self):
        self.upload([self.spec.example])
        vid = self.own_videos()[0]["id"]
        past = self.client.post(f"/api/videos/{vid}/schedule", json={"publish_at": "2020-01-01T10:00"})
        self.assertEqual(past.status_code, 400)
        ok = self.client.post(f"/api/videos/{vid}/schedule", json={"publish_at": "2031-01-02T07:15"}).json()
        self.assertEqual(ok["publish_at"], "2031-01-02T07:15")
        with db.session() as conn:
            published = conn.execute("SELECT id FROM videos WHERE status = 'published' LIMIT 1").fetchone()[0]
        self.assertIn("can't be rescheduled", self.client.post(f"/api/videos/{published}/schedule", json={"publish_at": "2031-01-01T10:00"}).json()["error"])

    def test_slots_are_validated_and_deduplicated(self):
        self.assertEqual(self.client.post(f"/api/channels/{self.focus_channel}/slots", json={"slots": ["24:00"]}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/channels/{self.focus_channel}/slots", json={"slots": []}).status_code, 400)
        r = self.client.post(f"/api/channels/{self.focus_channel}/slots", json={"slots": ["21:00", "08:00", "08:00"]}).json()
        self.assertEqual(r["slots"], ["08:00", "21:00"])

    def test_next_free_slots_skip_taken_times(self):
        with db.session() as conn:
            queue.set_slots(conn, self.focus_channel, ["10:00"])
            conn.execute("DELETE FROM videos WHERE channel_id = ? AND status != 'published'", (self.focus_channel,))
            after = timeutil.parse("2031-03-01T12:00")
            first = queue.next_free_slots(conn, self.focus_channel, 2, after)
            self.assertEqual(first, ["2031-03-02T10:00", "2031-03-03T10:00"])
            conn.execute("INSERT INTO videos (channel_id, video_ref, title, status, publish_at, created_at) VALUES (?, 'x', 'x', 'scheduled', '2031-03-02T10:00', 'now')", (self.focus_channel,))
            self.assertEqual(queue.next_free_slots(conn, self.focus_channel, 1, after), ["2031-03-03T10:00"])

    def test_render_needs_content_and_a_workflow(self):
        with db.session() as conn:
            mock_video = conn.execute("SELECT id FROM videos WHERE status = 'scheduled' LIMIT 1").fetchone()[0]
        self.assertIn("no slide content", self.client.post(f"/api/videos/{mock_video}/render").json()["error"])
        self.upload([get_spec("crime_files").example], channel_id=self._channel("crime_files"), niche="crime_files")
        crime = self.own_videos()[0]["id"]
        self.assertIn("isn't built yet", self.client.post(f"/api/videos/{crime}/render").json()["error"])

    def test_youtube_schedule_needs_a_rendered_video(self):
        self.upload([self.spec.example])
        vid = self.own_videos()[0]["id"]
        self.assertIn("Render the video first", self.client.post(f"/api/videos/{vid}/youtube").json()["error"])

    def _channel(self, niche):
        with db.session() as conn:
            return conn.execute("SELECT id FROM channels WHERE niche = ? AND connection = 'connected' LIMIT 1", (niche,)).fetchone()[0]


class TestAudio(HubTestCase):
    def test_non_audio_files_are_refused(self):
        r = self.client.post("/audio/focus_habits", data={"licence": ""},
                             files=[("files", ("notes.txt", b"hello", "text/plain")), ("files", ("fake.mp3", b"not audio", "audio/mpeg"))])
        self.assertIn("notes.txt: use one of", r.text)
        self.assertIn("fake.mp3: not a playable audio file", r.text)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audio").fetchone()[0], 0)

    def test_choose_audio_avoids_the_last_track(self):
        with db.session() as conn:
            for name in ("a", "b"):
                conn.execute("INSERT INTO audio (niche, title, filename, uploaded_at) VALUES ('focus_habits', ?, ?, 'now')", (name, name + ".mp3"))
            conn.execute("UPDATE audio SET last_used_at = '2026-01-01T10:00' WHERE title = 'a'")
            for _ in range(10):
                self.assertEqual(queue.choose_audio(conn, "focus_habits")["title"], "b")
            self.assertIsNone(queue.choose_audio(conn, "crime_files"))


if __name__ == "__main__":
    unittest.main()
