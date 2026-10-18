"""Tests for publishing.youtube with fake Google API services."""
import datetime as dt
import json
import os
import shutil
import tempfile
import unittest

import httplib2
from googleapiclient.errors import HttpError

from publishing import youtube as yt


class FakeRequest:
    def __init__(self, result=None, error=None, chunks=None):
        self.result, self.error, self.chunks = result, error, list(chunks or [])

    def execute(self, num_retries=0):
        if self.error:
            raise self.error
        return self.result

    def next_chunk(self):
        if self.error:
            raise self.error
        return self.chunks.pop(0)


class FakeResource:
    def __init__(self, service, name):
        self.service, self.name = service, name

    def __getattr__(self, method):
        def call(**kwargs):
            self.service.calls.append((self.name, method, kwargs))
            return self.service.responses[(self.name, method)]
        return call


class FakeService:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __getattr__(self, name):
        return lambda: FakeResource(self, name)


def http_error(status, reason):
    content = json.dumps({"error": {"message": reason, "errors": [{"reason": reason}]}}).encode()
    return HttpError(httplib2.Response({"status": status}), content)


class TestBodyAndTime(unittest.TestCase):
    def test_local_time_becomes_utc(self):
        self.assertEqual(yt.to_utc_rfc3339("2026-10-25T19:00", "Asia/Kolkata"), "2026-10-25T13:30:00Z")
        self.assertEqual(yt.to_utc_rfc3339("2026-07-01T09:00", "America/New_York"), "2026-07-01T13:00:00Z")

    def test_upload_body_is_private_scheduled_and_clean(self):
        body = yt.upload_body("Focus <tips>", "Line one\n<b>bold</b>", ["focus", "deep work"], "2026-10-25T13:30:00Z", "27", "en")
        self.assertEqual(body["status"], {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                                          "containsSyntheticMedia": True, "publishAt": "2026-10-25T13:30:00Z"})
        self.assertEqual(body["snippet"]["title"], "Focus ‹tips›")
        self.assertNotIn("<", body["snippet"]["description"])
        self.assertEqual(body["snippet"]["tags"], ["focus", "deep work"])
        self.assertNotIn("publishAt", yt.upload_body("T", "", [], None)["status"])

    def test_tags_are_cut_at_youtubes_500_character_limit(self):
        tags = yt.upload_body("T", "", ["word%03d" % i for i in range(100)], None)["snippet"]["tags"]
        self.assertLessEqual(sum(len(t) for t in tags) + len(tags) - 1, 500)
        self.assertGreater(len(tags), 50)

    def test_empty_title_is_refused(self):
        with self.assertRaises(yt.YouTubeError):
            yt.upload_body("  ", "", [], None)


class TestClientConfig(unittest.TestCase):
    def test_accepts_web_and_installed_clients(self):
        for kind in ("web", "installed"):
            cfg = yt.parse_client_config(json.dumps({kind: {"client_id": "id", "client_secret": "s"}}))
            self.assertEqual(cfg["kind"], kind)

    def test_rejects_other_files(self):
        for text in ("not json", json.dumps({"type": "service_account"}), json.dumps({"web": {"client_id": "id"}})):
            with self.assertRaises(yt.YouTubeError):
                yt.parse_client_config(text)


class TestCalls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_my_channel(self):
        svc = FakeService({("channels", "list"): FakeRequest({"items": [{
            "id": "UC123", "snippet": {"title": "Focus Daily", "customUrl": "@focusdaily"},
            "statistics": {"subscriberCount": "1500"}, "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]})})
        self.assertEqual(yt.my_channel(svc), {"id": "UC123", "title": "Focus Daily", "handle": "@focusdaily", "subscribers": 1500, "uploads_playlist": "UU123"})
        self.assertTrue(svc.calls[0][2]["mine"])

    def test_account_without_channel(self):
        with self.assertRaises(yt.YouTubeError):
            yt.my_channel(FakeService({("channels", "list"): FakeRequest({"items": []})}))

    def test_upload_returns_id_and_reports_progress(self):
        path = os.path.join(self.tmp, "v.mp4")
        with open(path, "wb") as f:
            f.write(b"\0" * 1024)

        class Status:
            def progress(self):
                return 0.5

        svc = FakeService({("videos", "insert"): FakeRequest(chunks=[(Status(), None), (None, {"id": "vid123"})])})
        seen = []
        self.assertEqual(yt.upload_video(svc, path, {"snippet": {}}, seen.append), "vid123")
        self.assertEqual(seen, [0.5])
        self.assertEqual(svc.calls[0][2]["part"], "snippet,status")

    def test_errors_are_translated(self):
        path = os.path.join(self.tmp, "v.mp4")
        open(path, "wb").close()
        cases = [(403, "quotaExceeded", yt.QuotaExceeded), (401, "authError", yt.NotAuthorized),
                 (403, "insufficientPermissions", yt.NotAuthorized), (400, "invalidTitle", yt.YouTubeError)]
        for status, reason, kind in cases:
            with self.subTest(reason=reason):
                svc = FakeService({("videos", "insert"): FakeRequest(error=http_error(status, reason))})
                with self.assertRaises(kind):
                    yt.upload_video(svc, path, {})

    def test_daily_stats_and_recent_videos(self):
        analytics = FakeService({("reports", "query"): FakeRequest({"rows": [["2026-10-01", 120, 50, 3, 1]]})})
        self.assertEqual(yt.daily_stats(analytics, dt.date(2026, 10, 1), dt.date(2026, 10, 2)),
                         [{"date": "2026-10-01", "views": 120, "watch_minutes": 50, "subs_gained": 3, "subs_lost": 1}])
        youtube = FakeService({
            ("playlistItems", "list"): FakeRequest({"items": [{"contentDetails": {"videoId": "v1"}}]}),
            ("videos", "list"): FakeRequest({"items": [{"id": "v1", "snippet": {"title": "A", "publishedAt": "2026-10-01T13:30:00Z"},
                                                        "status": {"privacyStatus": "public"}, "contentDetails": {"duration": "PT1M5S"},
                                                        "statistics": {"viewCount": "900", "likeCount": "40"}}]}),
        })
        video = yt.recent_videos(youtube, "UU1")[0]
        self.assertEqual((video["views"], video["likes"], video["comments"], video["duration_s"]), (900, 40, 0, 65.0))

    def test_set_publish_time_only_for_private_videos(self):
        svc = FakeService({("videos", "list"): FakeRequest({"items": [{"status": {"privacyStatus": "private", "publishAt": "old"}}]}),
                           ("videos", "update"): FakeRequest({})})
        yt.set_publish_time(svc, "v1", "2026-11-01T13:30:00Z")
        update = svc.calls[-1][2]
        self.assertEqual(update["body"], {"id": "v1", "status": {"privacyStatus": "private", "publishAt": "2026-11-01T13:30:00Z"}})
        public = FakeService({("videos", "list"): FakeRequest({"items": [{"status": {"privacyStatus": "public"}}]})})
        with self.assertRaises(yt.YouTubeError):
            yt.set_publish_time(public, "v1", "2026-11-01T13:30:00Z")


if __name__ == "__main__":
    unittest.main()
