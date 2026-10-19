"""AI Optimizer phase (b): channel analysis, suggestions for videos on YouTube, Apply with backup, Rollback, 7-day warning.

YouTube and Gemini are fakes; the fake YouTube answers by what is asked, so the real
publishing.youtube functions run against it.
"""
import datetime as dt
import json
import unittest
from unittest import mock

from publishing import youtube as yt
from tests.test_optimizer import FakeModel, answer
from tests.test_webapp import HubTestCase
from tests.test_youtube import FakeRequest, http_error
from webapp import channel_audit, db, metadata_apply, optimizer, timeutil, youtube_sync


def analysis_answer(**overrides):
    a = answer(health_score=42, summary="Few people find it. Better search words help.",
               reasons=[{"reason": "Almost no search traffic", "number": "0.9% search"}, {"reason": "Vague", "number": "none"}],
               actions=["Use 'haath dhona' first in the title", "Post one Short a day", "Make a playlist", "Turn on comments", "Add an end screen",
                        "Use Devanagari titles", "Keep Shorts under 15 s"],
               ideas=[{"title": "दांत साफ़ करो", "why": "Builds on the best video (55 views)"}, {"title": "Pani bachao", "why": "Same habit series"},
                      {"title": "Comment challenge", "why": "Ask kids to comment"}])
    a.update(overrides)
    return a


class FakeYouTube:
    """Just enough of the Data API: channels, playlistItems, playlists, videos.list/update."""

    def __init__(self, videos):
        self.store = videos  # id -> {"snippet": ..., "status": ..., "contentDetails": ..., "statistics": ...}
        self.calls, self.update_error = [], None

    def channels(self):
        return mock.Mock(list=lambda **k: self._log("channels.list", k, FakeRequest({"items": [{
            "id": "UCleo", "snippet": {"title": "Leo", "customUrl": "@leo"}, "statistics": {"subscriberCount": "12"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UUleo"}}}]})))

    def playlistItems(self):
        return mock.Mock(list=lambda **k: self._log("playlistItems.list", k, FakeRequest({"items": [{"contentDetails": {"videoId": i}} for i in self.store]})))

    def playlists(self):
        return mock.Mock(list=lambda **k: self._log("playlists.list", k, FakeRequest({"items": []})))

    def videos(self):
        def list_(**k):
            ids = k["id"].split(",")
            return self._log("videos.list", k, FakeRequest({"items": [dict(self.store[i], id=i) for i in ids if i in self.store]}))

        def update(**k):
            if self.update_error:
                return self._log("videos.update", k, FakeRequest(error=self.update_error))
            body = k["body"]
            self.store[body["id"]]["snippet"] = dict(self.store[body["id"]]["snippet"], **body["snippet"])
            return self._log("videos.update", k, FakeRequest({"id": body["id"], "snippet": self.store[body["id"]]["snippet"]}))
        return mock.Mock(list=list_, update=update)

    def _log(self, name, kwargs, request):
        self.calls.append((name, kwargs))
        return request


class FakeAnalytics:
    def __init__(self, ids):
        self.ids, self.queries = ids, []

    def reports(self):
        return mock.Mock(query=self.query)

    def query(self, **k):
        self.queries.append(k)
        dims = k.get("dimensions")
        if dims == "day":
            start = dt.date.fromisoformat(k["startDate"])
            return FakeRequest({"rows": [[(start + dt.timedelta(days=i)).isoformat(), 10, 2, 0, 0] for i in range((dt.date.fromisoformat(k['endDate']) - start).days + 1)]})
        if dims == "video":
            return FakeRequest({"rows": [[vid, 60 - n * 7, 5, 11, 95.0 - n * 9, 3, 1, 0] for n, vid in enumerate(self.ids)]})
        if dims == "insightTrafficSourceType":
            return FakeRequest({"rows": [["YT_CHANNEL", 63], ["SHORTS", 48], ["EXT_URL", 32], ["SUBSCRIBER", 6]]})
        if dims == "creatorContentType":
            return FakeRequest({"rows": [["shorts", 149, 13, 98.6]]})
        return FakeRequest(error=http_error(400, "The query is not supported."))  # impressions / CTR


class ChannelCase(HubTestCase):
    """A real, connected channel with 6 Made for Kids Shorts on a fake YouTube."""

    def setUp(self):
        super().setUp()
        with db.session() as conn:
            self.ch = youtube_sync.add_channel(conn, "Leo Ki Pathshala", "focus_habits", "10:00")
            conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = 'UCleo' WHERE id = ?", (self.ch,))
            db.set_setting(conn, "gemini_model", "gemini-test-flash-lite")
        now = timeutil.now_local()
        self.ids = [f"vid{n}" for n in range(6)]
        self.yt = FakeYouTube({vid: {
            "snippet": {"title": f"Khana Waste Mat Karo {n} | Leo Ki Pathshala #shorts", "description": "", "tags": ["leo"],
                        "categoryId": "27", "defaultLanguage": "hi", "publishedAt": (now - dt.timedelta(days=10 + n)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "status": {"privacyStatus": "public", "madeForKids": True, "selfDeclaredMadeForKids": True},
            "contentDetails": {"duration": "PT11S"}, "statistics": {"viewCount": str(60 - n * 7), "likeCount": "3"}} for n, vid in enumerate(self.ids)})
        self.an = FakeAnalytics(self.ids)
        for target in ("webapp.youtube_sync._services",):
            p = mock.patch(target, return_value=(self.yt, self.an))
            p.start()
            self.addCleanup(p.stop)
        for p in (mock.patch("webapp.ai_drafts.api_key", return_value="AIzaTEST"), mock.patch("webapp.channel_audit.threading.Thread"),
                  mock.patch("webapp.optimizer.threading.Thread")):
            p.start()
            self.addCleanup(p.stop)

    def analyse(self, replies=None, video_limit="10"):
        r = self.client.post(f"/channels/{self.ch}/analysis", data={"video_limit": video_limit}, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.headers.get("location"))
        audit_id = int(r.headers["location"].rsplit("/", 1)[-1])
        self.model = FakeModel(replies if replies is not None else [analysis_answer() for _ in self.ids])
        channel_audit.run(audit_id, client=self.model)
        return audit_id

    def suggestion(self, audit_id, n=0):
        with db.session() as conn:
            return dict(conn.execute("SELECT * FROM video_suggestions WHERE audit_id = ? ORDER BY id", (audit_id,)).fetchall()[n])

    def apply(self, sid, **form):
        data = {"title": "खाना वेस्ट मत करो | Leo Ki Pathshala #shorts", "description": "नई जानकारी\n#GoodHabits", "tags": "khana waste mat karo, good habits",
                "approve": "yes"}
        data.update(form)
        return self.client.post(f"/suggestions/{sid}/apply", data=data, follow_redirects=False)

    def changes(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM metadata_changes ORDER BY id")]


class TestChannelAnalysis(ChannelCase):
    # ---------- analysis ----------

    def test_analysis_report_with_real_numbers(self):
        audit_id = self.analyse()
        with db.session() as conn:
            audit = channel_audit.load(conn, audit_id)
        self.assertEqual(audit["status"], "ready")
        r = audit["report"]
        self.assertIsNone(r["reach"])  # the Analytics API doesn't serve impressions: phase 2
        keys = {f["key"] for f in r["findings"]}
        self.assertNotIn("recommended", keys)  # 54 of 149 views (36%) came from recommendations
        self.assertNotIn("trend_down", keys)  # steady daily views; YouTube's late days don't count as a drop
        self.assertIn("search", keys)
        self.assertIn("no_playlists", keys)
        self.assertIn("no_description", keys)
        self.assertEqual(r["numbers"]["recommended_pct"], round((48 + 6) / 149 * 100, 1))
        self.assertEqual(len(audit["suggestions"]), 6)
        self.assertTrue(all(s["status"] == "ready" for s in audit["suggestions"]))

        page = self.client.get(f"/channels/{self.ch}/analysis/{audit_id}").text
        self.assertIn("holding the channel back", page)
        self.assertIn("Videos to improve", page)
        self.assertIn('data-state="review"', page)
        self.assertIn("Impressions and click-through rate", page)
        self.assertIn("Reporting API", page)
        self.assertIn("Apply to YouTube", page)
        self.assertIn("Live on YouTube now", page)
        channel_page = self.client.get(f"/channels/{self.ch}").text
        self.assertIn("AI Optimizer", channel_page)
        self.assertIn("Open report and suggestions", channel_page)
        # read-only: nothing was written to YouTube
        self.assertFalse([c for c in self.yt.calls if c[0] == "videos.update"])

    def test_gemini_gets_findings_and_kids_rules_and_drops_unfollowable_advice(self):
        audit_id = self.analyse()
        prompt = self.model.prompts[0][0]
        self.assertIn("NUMBERS FROM YOUTUBE ANALYTICS", prompt)
        self.assertTrue(any("% viewed on average" in p for p, _ in self.model.prompts))
        self.assertIn("Never ask viewers to comment", prompt)  # from each video's own live Made for Kids setting
        self.assertIn("end screens", prompt)
        self.assertIn("health_score", self.model.prompts[0][1]["properties"])
        with db.session() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM video_suggestions WHERE audit_id = ?", (audit_id,))]
        s = next(r for r in rows if not any(f.startswith("Not enough") for f in json.loads(r["context_json"])["findings"]))
        pkg = json.loads(s["package_json"])
        self.assertEqual(pkg["health_score"], 42)
        self.assertEqual(pkg["reasons"], [{"reason": "Almost no search traffic", "number": "0.9% search"}])  # "none" isn't a number
        self.assertFalse(any("comment" in a.lower() or "end screen" in a.lower() for a in pkg["actions"]))
        self.assertEqual(len(pkg["ideas"]), 2)  # the comment challenge is left out
        self.assertEqual(s["made_for_kids"], 1)

    def test_video_with_too_few_views_gets_no_invented_reasons(self):
        audit_id = self.analyse()
        with db.session() as conn:
            rows = conn.execute("SELECT * FROM video_suggestions WHERE audit_id = ?", (audit_id,)).fetchall()
        few = [r for r in rows if any(f.startswith("Not enough data yet") for f in json.loads(r["context_json"])["findings"])]
        self.assertTrue(few)
        pkg = json.loads(few[0]["package_json"])
        self.assertEqual(pkg["reasons"], [])
        self.assertTrue(pkg["too_little_data"])

    def test_without_gemini_the_report_still_saves(self):
        with mock.patch("webapp.ai_drafts.api_key", return_value=None):
            audit_id = self.analyse(replies=[])
        with db.session() as conn:
            audit = channel_audit.load(conn, audit_id)
        self.assertEqual(audit["status"], "ready")
        self.assertIn("Gemini API key", audit["report"]["gemini_note"])
        self.assertEqual(audit["suggestions"], [])

    def test_quota_and_sign_in_problems_are_readable(self):
        with db.session() as conn:
            audit_id = channel_audit.start(conn, self.ch)
        self.an.query = lambda **k: FakeRequest(error=http_error(403, "quotaExceeded"))
        channel_audit.run(audit_id, client=FakeModel([]))
        with db.session() as conn:
            a = conn.execute("SELECT status, error FROM channel_audits WHERE id = ?", (audit_id,)).fetchone()
        self.assertEqual(a["status"], "failed")
        self.assertIn("quota", a["error"])
        self.assertIn("failed", self.client.get(f"/channels/{self.ch}").text)

    def test_only_real_connected_channels(self):
        r = self.client.post(f"/channels/{self.focus_channel}/analysis", data={"video_limit": "10"}, follow_redirects=False)
        self.assertIn("Only+a+real+channel", r.headers["location"])
        with db.session() as conn:
            conn.execute("UPDATE channels SET connection = 'expired' WHERE id = ?", (self.ch,))
        r = self.client.post(f"/channels/{self.ch}/analysis", data={"video_limit": "10"}, follow_redirects=False)
        self.assertIn("expired", r.headers["location"])
        with db.session() as conn:
            conn.execute("UPDATE channels SET connection = 'connected' WHERE id = ?", (self.ch,))
        self.assertIn("Pick+how+many", self.client.post(f"/channels/{self.ch}/analysis", data={"video_limit": "7"}, follow_redirects=False).headers["location"])

    # ---------- apply on YouTube ----------

    def test_apply_backs_up_logs_and_sends_only_the_snippet(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        yid = json.loads(s["context_json"])["live"]["id"]
        before = dict(self.yt.store[yid]["snippet"])
        r = self.apply(s["id"])
        self.assertIn("Changed+the", r.headers["location"])
        update = [c for c in self.yt.calls if c[0] == "videos.update"]
        self.assertEqual(len(update), 1)
        self.assertEqual(update[0][1]["part"], "snippet")
        body = update[0][1]["body"]
        self.assertNotIn("status", body)  # Made for Kids and privacy can't change
        self.assertEqual(body["snippet"]["categoryId"], "27")
        self.assertEqual(body["snippet"]["defaultLanguage"], "hi")
        self.assertEqual(self.yt.store[yid]["status"]["madeForKids"], True)

        log = self.changes()
        self.assertEqual({c["field"] for c in log}, {"title", "description", "tags"})
        self.assertTrue(all(c["status"] == "applied" and c["youtube_video_id"] == yid for c in log))
        by = {c["field"]: c for c in log}
        self.assertEqual(by["title"]["old_value"], before["title"])
        self.assertEqual(json.loads(by["tags"]["old_value"]), ["leo"])
        self.assertEqual(by["title"]["new_value"], "खाना वेस्ट मत करो | Leo Ki Pathshala #shorts")
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT title FROM videos WHERE youtube_video_id = ?", (yid,)).fetchone()[0], by["title"]["new_value"])
            self.assertEqual(conn.execute("SELECT units FROM quota_usage").fetchone()[0] >= metadata_apply.EDIT_COST, True)
        self.assertIn("Changes on YouTube", self.client.get(f"/channels/{self.ch}").text)

    def test_rollback_restores_the_backup(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        yid = json.loads(s["context_json"])["live"]["id"]
        before = dict(self.yt.store[yid]["snippet"])
        self.apply(s["id"])
        r = self.client.post(f"/suggestions/{s['id']}/undo", follow_redirects=False)
        self.assertIn("Rolled+back", r.headers["location"])
        now = self.yt.store[yid]["snippet"]
        self.assertEqual((now["title"], now["description"], now["tags"]), (before["title"], before["description"], before["tags"]))
        log = self.changes()
        self.assertEqual({c["status"] for c in log if c["action"] == "apply"}, {"rolled_back"})
        self.assertEqual(len([c for c in log if c["action"] == "rollback"]), 3)
        self.assertIn("already+rolled+back", self.client.post(f"/suggestions/{s['id']}/undo", follow_redirects=False).headers["location"])

    def test_rollback_refuses_after_an_edit_in_studio(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        yid = json.loads(s["context_json"])["live"]["id"]
        self.apply(s["id"])
        self.yt.store[yid]["snippet"]["title"] = "Edited in Studio"
        group = self.changes()[0]["change_group"]
        r = self.client.post(f"/changes/{group}/rollback", data={"back": f"/channels/{self.ch}"}, follow_redirects=False)
        self.assertTrue(r.headers["location"].startswith(f"/channels/{self.ch}?problem="))
        self.assertIn("changed+on+YouTube+after", r.headers["location"])
        self.assertEqual(self.yt.store[yid]["snippet"]["title"], "Edited in Studio")

    def test_seven_day_warning_needs_a_second_tick(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        self.apply(s["id"])
        r = self.apply(s["id"], title="दूसरा शीर्षक | Leo Ki Pathshala #shorts")
        self.assertIn("less+than+7+days+ago", r.headers["location"])
        self.assertEqual(len([c for c in self.yt.calls if c[0] == "videos.update"]), 1)
        self.assertIn("Change it anyway", self.client.get(f"/channels/{self.ch}/analysis/{audit_id}").text)
        r = self.apply(s["id"], title="दूसरा शीर्षक | Leo Ki Pathshala #shorts", confirm_recent="yes")
        self.assertIn("Changed+the", r.headers["location"])
        self.assertEqual(len([c for c in self.yt.calls if c[0] == "videos.update"]), 2)

    def test_stale_preview_is_refused(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        yid = json.loads(s["context_json"])["live"]["id"]
        self.yt.store[yid]["snippet"]["description"] = "Someone typed this in Studio"
        r = self.apply(s["id"])
        self.assertIn("changed+on+YouTube+since+this+preview", r.headers["location"])
        self.assertFalse([c for c in self.yt.calls if c[0] == "videos.update"])
        self.assertEqual(self.changes(), [])
        self.assertIn("Someone typed this in Studio", self.client.get(f"/channels/{self.ch}/analysis/{audit_id}").text)

    def test_youtube_failure_keeps_the_backup_and_says_nothing_changed(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        self.yt.update_error = http_error(403, "quotaExceeded")
        r = self.apply(s["id"])
        self.assertIn("quota+is+used+up%2C+so+nothing+was+changed", r.headers["location"])
        self.assertEqual({c["status"] for c in self.changes()}, {"failed"})
        self.assertNotIn("Roll back", self.client.get(f"/channels/{self.ch}").text.split("Changes on YouTube")[1].split("</section>")[0])

    def test_limits_and_approval_on_youtube_too(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        self.assertIn("approve", self.apply(s["id"], approve="").headers["location"])
        self.assertIn("bytes", self.apply(s["id"], description="क" * 1700).headers["location"])
        self.assertIn("characters", self.apply(s["id"], tags=", ".join(f"tag{i:02d}" + "x" * 36 for i in range(13))).headers["location"])
        self.assertFalse([c for c in self.yt.calls if c[0] == "videos.update"])

    def test_bad_rollback_input(self):
        self.assertEqual(self.client.post("/changes/not-a-group/rollback", data={"back": "/"}).status_code, 404)
        r = self.client.post(f"/changes/{'a' * 32}/rollback", data={"back": "https://evil.example"}, follow_redirects=False)
        self.assertTrue(r.headers["location"].startswith("/?problem="))


class TestYouTubeEdits(unittest.TestCase):
    def test_network_errors_are_readable(self):
        class Broken:
            def execute(self, num_retries=0):
                raise TimeoutError("timed out")
        with self.assertRaises(yt.YouTubeError) as e:
            yt._call(Broken(), retries=2)
        self.assertIn("Couldn't reach YouTube", str(e.exception))

    def test_update_refuses_over_limit_and_missing_category(self):
        live = {"id": "v", "category_id": "27"}
        with self.assertRaises(yt.YouTubeError):
            yt.update_video_metadata(None, live, "a" * 101, "", [])
        with self.assertRaises(yt.YouTubeError):
            yt.update_video_metadata(None, {"id": "v"}, "ok", "", [])


if __name__ == "__main__":
    unittest.main()


class TestReports(ChannelCase):
    """Phase (c): saved reports, month-to-month comparison and the results of changes."""

    def test_second_analysis_compares_with_the_first(self):
        first = self.analyse()
        self.yt.store["vid0"]["snippet"]["description"] = "x" * 200  # fix one thing on YouTube
        second = self.analyse()
        page = self.client.get(f"/channels/{self.ch}/analysis/{second}").text
        self.assertIn("Since the previous analysis", page)
        self.assertIn("All analyses", page)
        self.assertIn(f"/channels/{self.ch}/analysis/{second}/compare/{first}", page)
        compare = self.client.get(f"/channels/{self.ch}/analysis/{second}/compare/{first}")
        self.assertEqual(compare.status_code, 200)
        self.assertIn("Still open", compare.text)
        self.assertIn("Health score", compare.text)
        # the order of the two IDs doesn't matter, but both must be this channel's
        self.assertEqual(self.client.get(f"/channels/{self.ch}/analysis/{first}/compare/{second}").status_code, 200)
        self.assertEqual(self.client.get(f"/channels/{self.focus_channel}/analysis/{second}/compare/{first}").status_code, 404)
        self.assertIn("Earlier analyses (1)", self.client.get(f"/channels/{self.ch}").text)

    def test_compare_lists_fixed_new_and_open(self):
        old = {"score": 40, "started_at": "2026-09-18T10:00", "report": {"numbers": {"views": 100, "avg_view_pct": 50.0, "recommended_pct": 10.0,
               "search_pct": 1.0, "likes_per_1000": 20.0}, "findings": [
                   {"key": "search", "severity": "medium", "title": "Search"}, {"key": "stale", "severity": "high", "title": "Stale"},
                   {"key": "engagement_ok", "severity": "info", "title": "fine"}]}}
        new = {"score": 55, "started_at": "2026-10-18T10:00", "report": {"numbers": {"views": 160, "avg_view_pct": 48.0, "recommended_pct": 30.0,
               "search_pct": 4.0, "likes_per_1000": 20.0}, "findings": [
                   {"key": "search", "severity": "medium", "title": "Search"}, {"key": "batches", "severity": "medium", "title": "Batches"}]}}
        d = channel_audit.compare(old, new)
        self.assertEqual([f["key"] for f in d["fixed"]], ["stale"])
        self.assertEqual([f["key"] for f in d["new"]], ["batches"])
        self.assertEqual([f["key"] for f in d["open"]], ["search"])
        self.assertEqual(d["days_apart"], 30)
        m = {x["label"]: x for x in d["metrics"]}
        self.assertEqual((m["Health score"]["diff"], m["Health score"]["good"]), (15, True))
        self.assertEqual((m["Average % viewed"]["diff"], m["Average % viewed"]["good"]), (-2.0, False))
        self.assertIsNone(m["Likes per 1,000 views"]["good"])

    def test_change_results_wait_then_measure(self):
        audit_id = self.analyse()
        s = self.suggestion(audit_id)
        self.apply(s["id"])
        with db.session() as conn:
            results = channel_audit.measure_changes(conn, self.ch, self.an, timeutil.now_local().date())
        self.assertEqual(results[0]["state"], "waiting")  # changed today: no "after" days yet
        ten_days_ago = timeutil.fmt(timeutil.now_local() - dt.timedelta(days=12))
        with db.session() as conn:
            conn.execute("UPDATE metadata_changes SET created_at = ?", (ten_days_ago,))
        self.an.query = lambda **k: FakeRequest({"rows": [
            [(dt.date.fromisoformat(k["startDate"]) + dt.timedelta(days=i)).isoformat(), 2 if i < 7 else 5] for i in range(15)]})
        with db.session() as conn:
            results = channel_audit.measure_changes(conn, self.ch, self.an, timeutil.now_local().date())
        self.assertEqual((results[0]["state"], results[0]["before"], results[0]["after"]), ("measured", 14, 35))
        self.assertEqual(results[0]["change_pct"], 150.0)

    def test_history_lists_every_analysis(self):
        self.analyse()
        self.analyse()
        with db.session() as conn:
            h = channel_audit.history(conn, self.ch)
        self.assertEqual(len(h), 2)
        self.assertGreater(h[0]["id"], h[1]["id"])
        self.assertIn("views", h[0]["numbers"])
