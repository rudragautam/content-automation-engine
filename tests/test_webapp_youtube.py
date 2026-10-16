"""Hub-level tests for the YouTube connection, uploads and sync, with fake Google services."""
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from tests.test_webapp import HubTestCase
from tests.test_youtube import FakeRequest, FakeService, http_error
from webapp import db, queue, youtube_sync


class TestYouTubeConnection(HubTestCase):
    def real_channel(self, name="Real Focus"):
        with db.session() as conn:
            return youtube_sync.add_channel(conn, name, "focus_habits", "10:00, 20:00")

    def save_client(self):
        youtube_sync.save_client_file(
            b'{"web": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "s", '
            b'"auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", '
            b'"redirect_uris": ["http://testserver/oauth/callback"]}}')

    def rendered_video(self, channel_id, publish_at="2031-05-04T19:00"):
        path = f"{self.tmp}/final.mp4"
        with open(path, "wb") as f:
            f.write(b"\0" * 2048)
        with db.session() as conn:
            conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = 'UCreal' WHERE id = ?", (channel_id,))
            return conn.execute(
                "INSERT INTO videos (channel_id, video_ref, title, description, tags, status, publish_at, video_path, created_at) "
                "VALUES (?, 'R1', 'Real video', 'Desc', 'focus, habits', 'rendered', ?, ?, 'now')", (channel_id, publish_at, path)).lastrowid

    def test_settings_page_shows_redirect_uri(self):
        self.assertIn("http://testserver/oauth/callback", self.client.get("/settings").text)

    def test_client_file_is_validated(self):
        r = self.client.post("/settings/client", files={"file": ("x.json", b'{"type": "service_account"}', "application/json")})
        self.assertIn("an OAuth client file", r.text)
        self.save_client()
        self.assertIn("Client file saved", self.client.get("/settings").text)

    def test_add_channel_validates_slots(self):
        self.assertIn("Not a time", self.client.post("/settings/channels", data={"name": "New", "niche": "focus_habits", "slots": "7pm"}).text)
        r = self.client.post("/settings/channels", data={"name": "New", "niche": "focus_habits", "slots": "07:00"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        with db.session() as conn:
            row = conn.execute("SELECT is_mock, connection FROM channels WHERE name = 'New'").fetchone()
        self.assertEqual(tuple(row), (0, "not_connected"))

    def test_connect_refuses_mock_channels_and_needs_a_client(self):
        self.assertIn("This is a mock channel", self.client.get(f"/oauth/start?channel={self.focus_channel}").text)
        real = self.real_channel()
        self.assertIn("Upload your Google OAuth client file", self.client.get(f"/oauth/start?channel={real}").text)

    def test_connect_redirects_to_google_with_offline_access(self):
        self.save_client()
        real = self.real_channel()
        location = self.client.get(f"/oauth/start?channel={real}", follow_redirects=False).headers["location"]
        self.assertTrue(location.startswith("https://accounts.google.com/"))
        self.assertIn("access_type=offline", location)
        self.assertIn("code_challenge=", location)

    def test_callback_with_unknown_state_is_refused(self):
        self.save_client()
        self.assertIn("expired or was already used", self.client.get("/oauth/callback?state=nope&code=x").text)

    def sign_in_as(self, found, form=None):
        """Start a connect from Settings and finish it as if Google signed in to `found`."""
        r = self.client.post("/settings/connect", data=form or {"niche": "science_quiz", "slots": "08:00, 18:30"}, follow_redirects=False)
        self.assertTrue(r.headers["location"].startswith("https://accounts.google.com/"))
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        with mock.patch("publishing.youtube.exchange_code", return_value=mock.Mock(refresh_token="r")),                 mock.patch("publishing.youtube.build_services", return_value=(None, None)),                 mock.patch("publishing.youtube.my_channel", return_value=found),                 mock.patch("publishing.youtube.save_credentials") as saved:
            page = self.client.get(f"/oauth/callback?state={state}&code=x")
        return page, saved

    def test_connect_from_settings_creates_the_channel_from_youtube(self):
        self.save_client()
        found = {"id": "UCsci", "title": "Science Sawaal", "handle": "@sciencesawaal", "subscribers": 42}
        page, saved = self.sign_in_as(found)
        self.assertIn("Connected to YouTube", page.text)
        self.assertIn("Science Sawaal", page.text)
        with db.session() as conn:
            row = conn.execute("SELECT * FROM channels WHERE youtube_channel_id = 'UCsci'").fetchone()
            times = [r[0] for r in conn.execute("SELECT time FROM channel_slots WHERE channel_id = ? ORDER BY time", (row["id"],))]
        self.assertEqual((row["name"], row["handle"], row["niche"], row["connection"], row["subscribers"], row["is_mock"]),
                         ("Science Sawaal", "@sciencesawaal", "science_quiz", "connected", 42, 0))
        self.assertEqual(times, ["08:00", "18:30"])
        self.assertEqual(saved.call_args[0][1], youtube_sync.token_path(row["id"]))

        # Connecting the same YouTube channel again renews its sign-in instead of adding a copy.
        with db.session() as conn:
            conn.execute("UPDATE channels SET connection = 'expired' WHERE id = ?", (row["id"],))
        self.sign_in_as(found, {"niche": "crime_files", "slots": "07:00"})
        with db.session() as conn:
            rows = conn.execute("SELECT id, niche, connection FROM channels WHERE youtube_channel_id = 'UCsci'").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(row["id"], "science_quiz", "connected")])

    def test_connect_from_settings_checks_input_and_cancel(self):
        self.assertIn("Upload your Google OAuth client file", self.client.post("/settings/connect", data={"niche": "focus_habits", "slots": "19:00"}).text)
        self.save_client()
        self.assertIn("Not a time", self.client.post("/settings/connect", data={"niche": "focus_habits", "slots": "7pm"}).text)
        self.assertIn("Pick a niche", self.client.post("/settings/connect", data={"niche": "nope", "slots": "19:00"}).text)
        r = self.client.post("/settings/connect", data={"niche": "focus_habits", "slots": "19:00"}, follow_redirects=False)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        page = self.client.get(f"/oauth/callback?state={state}&error=access_denied")
        self.assertIn("You cancelled the sign-in", page.text)
        self.assertIn("Connect a YouTube channel", page.text)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM channels WHERE is_mock = 0").fetchone()[0], 0)

    def test_bind_channel_refuses_mixups(self):
        a, b = self.real_channel("A"), self.real_channel("B")
        found = {"id": "UCa", "title": "Channel A", "handle": "@a", "subscribers": 10}
        with db.session() as conn:
            youtube_sync.bind_channel(conn, a, found)
            self.assertEqual(conn.execute("SELECT connection FROM channels WHERE id = ?", (a,)).fetchone()[0], "connected")
            with self.assertRaises(queue.ActionError):
                youtube_sync.bind_channel(conn, b, found)  # same YouTube channel twice
            with self.assertRaises(queue.ActionError):
                youtube_sync.bind_channel(conn, a, dict(found, id="UCother"))  # signed in as a different channel

    def test_upload_schedules_with_utc_time_and_counts_quota(self):
        vid = self.rendered_video(self.real_channel())
        with mock.patch("webapp.youtube_sync.threading.Thread"):
            self.assertEqual(self.client.post(f"/api/videos/{vid}/youtube").json()["status"], "uploading")
        fake = FakeService({("videos", "insert"): FakeRequest(chunks=[(None, {"id": "yt999"})])})
        with db.session() as conn:
            before = conn.execute("SELECT COALESCE(SUM(units), 0) FROM quota_usage").fetchone()[0]
        youtube_sync.upload_now(vid, services=(fake, None))
        body = fake.calls[0][2]["body"]
        self.assertEqual(body["status"]["publishAt"], "2031-05-04T13:30:00Z")
        self.assertEqual(body["snippet"]["tags"], ["focus", "habits"])
        with db.session() as conn:
            row = conn.execute("SELECT status, youtube_video_id FROM videos WHERE id = ?", (vid,)).fetchone()
            after = conn.execute("SELECT COALESCE(SUM(units), 0) FROM quota_usage").fetchone()[0]
        self.assertEqual(tuple(row), ("scheduled", "yt999"))
        self.assertEqual(after - before, 1600)
        self.assertIn("already on YouTube", self.client.post(f"/api/videos/{vid}/delete").json()["error"])

    def test_upload_close_to_publish_time_is_refused(self):
        from webapp import timeutil
        soon = timeutil.fmt(timeutil.now_local() + __import__("datetime").timedelta(minutes=5))
        vid = self.rendered_video(self.real_channel(), publish_at=soon)
        self.assertIn("less than 15 minutes away", self.client.post(f"/api/videos/{vid}/youtube").json()["error"])

    def test_failed_upload_can_be_retried(self):
        vid = self.rendered_video(self.real_channel())
        fake = FakeService({("videos", "insert"): FakeRequest(error=http_error(403, "quotaExceeded"))})
        youtube_sync.upload_now(vid, services=(fake, None))
        with db.session() as conn:
            row = conn.execute("SELECT status, error FROM videos WHERE id = ?", (vid,)).fetchone()
        self.assertEqual(row["status"], "rendered")
        self.assertIn("quota is used up", row["error"])

    def test_reschedule_moves_the_time_on_youtube(self):
        vid = self.rendered_video(self.real_channel())
        with db.session() as conn:
            conn.execute("UPDATE videos SET status = 'scheduled', youtube_video_id = 'yt1' WHERE id = ?", (vid,))
        fake = FakeService({("videos", "list"): FakeRequest({"items": [{"status": {"privacyStatus": "private"}}]}),
                            ("videos", "update"): FakeRequest({})})
        with db.session() as conn:
            youtube_sync.reschedule(conn, vid, "2031-06-01T08:00", services=(fake, None))
        self.assertEqual(fake.calls[-1][2]["body"]["status"]["publishAt"], "2031-06-01T02:30:00Z")

    def test_failed_youtube_reschedule_keeps_the_old_time(self):
        vid = self.rendered_video(self.real_channel())
        with db.session() as conn:
            conn.execute("UPDATE videos SET status = 'scheduled', youtube_video_id = 'yt1' WHERE id = ?", (vid,))
        fake = FakeService({("videos", "list"): FakeRequest({"items": [{"status": {"privacyStatus": "public"}}]})})
        with self.assertRaises(queue.ActionError):
            with db.session() as conn:
                youtube_sync.reschedule(conn, vid, "2031-06-01T08:00", services=(fake, None))
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT publish_at FROM videos WHERE id = ?", (vid,)).fetchone()[0], "2031-05-04T19:00")

    def test_sync_pulls_stats_and_videos(self):
        real = self.real_channel()
        with db.session() as conn:
            conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = 'UCreal' WHERE id = ?", (real,))
        youtube = FakeService({
            ("channels", "list"): FakeRequest({"items": [{"id": "UCreal", "snippet": {"title": "Real"}, "statistics": {"subscriberCount": "321"},
                                                          "contentDetails": {"relatedPlaylists": {"uploads": "UUreal"}}}]}),
            ("playlistItems", "list"): FakeRequest({"items": [{"contentDetails": {"videoId": "v1"}}]}),
            ("videos", "list"): FakeRequest({"items": [{"id": "v1", "snippet": {"title": "Live one", "publishedAt": "2026-10-01T13:30:00Z"},
                                                        "status": {"privacyStatus": "public"}, "contentDetails": {"duration": "PT30S"},
                                                        "statistics": {"viewCount": "77"}}]}),
        })
        analytics = FakeService({("reports", "query"): FakeRequest({"rows": [["2026-10-01", 120, 50, 3, 1], ["2026-10-02", 90, 40, 2, 0]]})})
        with db.session() as conn:
            self.assertEqual(youtube_sync.sync_channel(conn, real, services=(youtube, analytics)), {"days": 2, "videos": 1})
            self.assertEqual(conn.execute("SELECT subscribers FROM channels WHERE id = ?", (real,)).fetchone()[0], 321)
            self.assertEqual(conn.execute("SELECT SUM(views) FROM daily_stats WHERE channel_id = ?", (real,)).fetchone()[0], 210)
            video = conn.execute("SELECT status, publish_at, views FROM videos WHERE youtube_video_id = 'v1'").fetchone()
        self.assertEqual(tuple(video), ("published", "2026-10-01T19:00", 77))

    def test_remove_mock_data_survives_restart(self):
        real = self.real_channel()
        self.assertIn("Removed 20 mock channels", self.client.post("/settings/remove-mock").text)
        self.client.__exit__(None, None, None)
        from webapp.app import app
        self.client = TestClient(app)
        self.client.__enter__()
        with db.session() as conn:
            self.assertEqual([r[0] for r in conn.execute("SELECT id FROM channels")], [real])
        self.assertNotIn("Mock data.", self.client.get("/").text)


if __name__ == "__main__":
    unittest.main()
