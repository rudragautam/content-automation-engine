"""AI Optimizer: the rule-based checks. Pure functions, no network."""
import datetime as dt
import unittest

from webapp import optimizer_checks as checks

TODAY = dt.date(2026, 10, 18)


def video(n, views=100, pct=80.0, short=True, days_ago=10, hour=9, **extra):
    published = dt.datetime.combine(TODAY - dt.timedelta(days=days_ago), dt.time(hour, 0), tzinfo=dt.timezone.utc)
    v = {"youtube_id": f"yt{n}", "video_id": n, "title": f"Video number {n} about good habits", "description": "x" * 150,
         "tags": ["a", "b", "c", "d", "e", "f"], "published_at": published.isoformat(), "duration_s": 12.0 if short else 300.0,
         "is_short": short, "privacy": "public", "views": views, "lifetime_views": views, "avg_view_pct": pct,
         "likes": views // 20, "shares": views // 100, "subs_gained": 1}
    v.update(extra)
    return v


def days(values, start_offset):
    """Daily rows ending `start_offset` days before today, oldest first."""
    return [{"date": (TODAY - dt.timedelta(days=start_offset + len(values) - i)).isoformat(), "views": v, "watch_minutes": v,
             "subs_gained": 1, "subs_lost": 0} for i, v in enumerate(values)]


def keys(findings):
    return [f["key"] for f in findings]


class TestNotEnoughData(unittest.TestCase):
    def test_small_channel_says_not_enough_data(self):
        f = checks.check_volume(40, 28)
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0]["title"].startswith("Not enough data yet"))
        self.assertEqual(f[0]["numbers"]["views in period"], 40)
        self.assertEqual(checks.check_volume(500, 28), [])

    def test_retention_needs_views_per_video(self):
        f = checks.check_retention([video(1, views=5), video(2, views=10)])
        self.assertEqual(keys(f), ["retention_short"])
        self.assertTrue(f[0]["title"].startswith("Not enough data yet"))

    def test_score_is_none_without_judgeable_findings(self):
        self.assertIsNone(checks.health_score([checks.not_enough("x", "y", {})]))
        self.assertEqual(checks.health_score([checks.finding("a", "high", "t", "d"), checks.finding("b", "low", "t", "d")]), 76)

    def test_trend_needs_an_earlier_period(self):
        f = checks.check_trend(days([10] * 28, 0), TODAY)
        self.assertTrue(f[0]["title"].startswith("Not enough data yet"))

    def test_video_findings_say_not_enough_data(self):
        lines = checks.video_findings(video(1, views=3), 80, 50)
        self.assertTrue(lines[0].startswith("Not enough data yet: 3 views"))


class TestChecks(unittest.TestCase):
    def test_low_retention_on_shorts_with_numbers(self):
        f = checks.check_retention([video(1, views=100, pct=40), video(2, views=100, pct=50), video(3, views=100, pct=95, short=False)])
        by = {x["key"]: x for x in f}
        self.assertEqual(by["retention_short"]["severity"], "high")
        self.assertEqual(by["retention_short"]["numbers"]["average % viewed"], 45.0)
        self.assertEqual(by["retention_short"]["videos"], ["yt1", "yt2"])
        self.assertEqual(by["retention_long_ok"]["severity"], "info")

    def test_some_low_retention_videos(self):
        f = checks.check_retention([video(1, pct=90), video(2, pct=95), video(3, pct=50)])
        self.assertEqual(f[0]["key"], "retention_short_some")
        self.assertEqual(f[0]["videos"], ["yt3"])

    def test_no_recommended_traffic(self):
        f = checks.check_traffic({"YT_CHANNEL": 63, "SHORTS": 10, "EXT_URL": 50, "SUBSCRIBER": 2, "YT_SEARCH": 1})
        by = {x["key"]: x for x in f}
        self.assertEqual(by["recommended"]["severity"], "high")
        self.assertEqual(by["recommended"]["numbers"]["recommended %"], 9.5)
        self.assertEqual(by["search"]["numbers"]["search %"], 0.8)
        self.assertIn("external", by)

    def test_balanced_traffic(self):
        f = checks.check_traffic({"SHORTS": 300, "YT_SEARCH": 80, "RELATED_VIDEO": 50})
        self.assertEqual(keys(f), ["traffic_ok"])

    def test_batch_uploads_and_gaps(self):
        vids = [video(i, days_ago=40) for i in range(5)] + [video(9, days_ago=20), video(10, days_ago=19), video(11, days_ago=18)]
        by = {x["key"]: x for x in checks.check_uploads(vids, TODAY)}
        self.assertEqual(by["batches"]["numbers"]["most in one day"], 5)
        self.assertEqual(by["stale"]["numbers"]["days since last upload"], 18)
        self.assertIn("gaps", by)
        self.assertEqual(by["gaps"]["numbers"]["longest gap (days)"], 20)

    def test_regular_uploads(self):
        vids = [video(i, days_ago=i * 2) for i in range(1, 8)]
        self.assertEqual(keys(checks.check_uploads(vids, TODAY)), ["uploads_ok"])

    def test_weak_metadata_and_no_playlists(self):
        vids = [video(i, title="Short", description="", tags=[]) for i in range(4)] + [video(9)]
        by = {x["key"]: x for x in checks.check_metadata(vids, 0)}
        self.assertEqual(by["no_description"]["severity"], "high")
        self.assertEqual(by["no_description"]["numbers"], {"videos": 4, "of": 5, "%": 80.0})
        self.assertIn("titles_short", by)
        self.assertIn("few_tags", by)
        self.assertIn("no_hashtags", by)
        self.assertIn("no_playlists", by)
        self.assertNotIn("no_playlists", keys(checks.check_metadata(vids, 2)))
        self.assertNotIn("no_playlists", keys(checks.check_metadata(vids, None)))  # unknown is not zero

    def test_format_mismatch(self):
        vids = [video(i, views=300) for i in range(3)] + [video(i + 10, views=40, short=False) for i in range(3)]
        f = checks.check_formats(vids, {})
        self.assertEqual(f[0]["key"], "formats")
        self.assertIn("Shorts do far better", f[0]["title"])
        self.assertEqual(checks.check_formats(vids[:3], {}), [])

    def test_falling_trend(self):
        daily = days([20] * 28, 28) + days([8] * 28, 0)
        f = checks.check_trend(daily, TODAY)
        self.assertEqual(f[0]["key"], "trend_down")
        self.assertEqual(f[0]["numbers"]["change %"], -60.0)
        self.assertEqual(f[0]["severity"], "high")
        self.assertEqual(checks.check_trend(days([10] * 28, 28) + days([30] * 28, 0), TODAY)[0]["key"], "trend_up")

    def test_engagement_per_1000(self):
        f = checks.check_engagement([video(1, views=1000, likes=5, shares=2, subs_gained=3)])
        self.assertEqual(f[0]["key"], "engagement")
        self.assertEqual(f[0]["numbers"], {"likes per 1,000 views": 5.0, "shares per 1,000 views": 2.0, "subscribers per 1,000 views": 3.0})

    def test_top_vs_bottom(self):
        top = [video(i, views=500, title="हाथ धोना सीखो बच्चों के लिए", hour=18) for i in range(3)]
        bottom = [video(i + 10, views=20, title="Habit", hour=6) for i in range(3)]
        f = checks.compare_top_bottom(top + bottom, TODAY)[0]
        self.assertEqual(f["key"], "top_bottom")
        self.assertEqual(f["numbers"]["top titles in Devanagari"], 3)
        self.assertEqual(f["numbers"]["bottom titles in Devanagari"], 0)
        self.assertIn("publish hour: top 18", f["detail"])
        new = [video(i, days_ago=1) for i in range(6)]  # too fresh to compare
        self.assertTrue(checks.compare_top_bottom(new, TODAY)[0]["title"].startswith("Not enough data yet"))

    def test_weakest_skips_fresh_videos_first(self):
        vids = [video(1, views=1000, days_ago=10), video(2, views=10, days_ago=10), video(3, views=0, days_ago=1), video(4, privacy="private")]
        self.assertEqual([v["youtube_id"] for v in checks.weakest(vids, TODAY, 2)], ["yt2", "yt1"])
        self.assertEqual(len(checks.weakest(vids, TODAY, 0)), 3)

    def test_run_checks_orders_by_severity(self):
        data = {"today": TODAY, "videos": [video(i, views=200, pct=40) for i in range(6)],
                "traffic": {"YT_CHANNEL": 900, "SHORTS": 100, "YT_SEARCH": 200}, "daily": days([40] * 28, 28) + days([40] * 28, 0),
                "playlists": 1, "content": {}}
        result = checks.run_checks(data)
        severities = [f["severity"] for f in result["findings"]]
        self.assertEqual(severities, sorted(severities, key=checks.SEVERITY_ORDER.get))
        self.assertEqual(result["numbers"]["avg_view_pct"], 40.0)
        self.assertEqual(result["numbers"]["recommended_pct"], 8.3)
        self.assertIsInstance(result["score"], int)


if __name__ == "__main__":
    unittest.main()
