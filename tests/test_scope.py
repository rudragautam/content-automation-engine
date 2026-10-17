"""Tests for the global channel filter (created status + one channel)."""
import unittest

from tests.test_webapp import HubTestCase
from webapp import db, scope
from webapp.analytics import kpis


class TestScope(HubTestCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            # Mock channels all carry a YouTube ID; add one planned channel that isn't on YouTube yet.
            self.planned = conn.execute(
                "INSERT INTO channels (name, handle, niche, connection, created_at, is_mock) VALUES ('Planned One', '', 'crime_files', 'not_connected', '2026-01-01', 0)").lastrowid
            self.live_count = conn.execute("SELECT COUNT(*) FROM channels WHERE COALESCE(youtube_channel_id, '') != ''").fetchone()[0]
            self.planned_ids = sorted(r[0] for r in conn.execute("SELECT id FROM channels WHERE COALESCE(youtube_channel_id, '') = ''"))

    def resolve(self, query, cookies=None):
        with db.session() as conn:
            return scope.resolve(conn, query, cookies or {})

    def test_defaults_to_everything(self):
        sc = self.resolve({})
        self.assertIsNone(sc["ids"])
        self.assertFalse(sc["active"])

    def test_created_split(self):
        live, planned = self.resolve({"created": "live"}), self.resolve({"created": "planned"})
        self.assertEqual(len(live["ids"]), self.live_count)
        self.assertNotIn(self.planned, live["ids"])
        self.assertEqual(sorted(planned["ids"]), self.planned_ids)
        self.assertIn(self.planned, planned["ids"])
        self.assertEqual(planned["label"], "Not created yet")

    def test_one_channel_and_mismatch_is_dropped(self):
        self.assertEqual(self.resolve({"ch": str(self.focus_channel)})["ids"], [self.focus_channel])
        # A live channel can't be picked while showing only channels not created yet.
        sc = self.resolve({"created": "planned", "ch": str(self.focus_channel)})
        self.assertIsNone(sc["channel"])
        self.assertEqual(sorted(sc["ids"]), self.planned_ids)
        self.assertIsNone(self.resolve({"ch": "999999"})["channel"])
        self.assertEqual(self.resolve({"created": "nonsense"})["created"], "all")

    def test_analytics_numbers_follow_the_filter(self):
        with db.session() as conn:
            everything = kpis(conn, 28)
            one = kpis(conn, 28, [self.focus_channel])
            none = kpis(conn, 28, [self.planned])
        self.assertGreater(everything["views"], one["views"])
        self.assertGreater(one["views"], 0)
        self.assertEqual((none["views"], none["subscribers"]), (0, 0))

    def test_pages_filter_and_remember_the_choice(self):
        r = self.client.get(f"/analytics?ch={self.focus_channel}")
        self.assertIn("Focus Daily", r.text)
        self.assertIn("1 channel ·", r.text)
        self.assertEqual(r.cookies.get("hub_channel"), str(self.focus_channel))
        # The next page, opened without parameters, keeps the same channel.
        dash = self.client.get("/").text
        self.assertIn("<h1>Focus Daily</h1>", dash)
        self.assertIn("Clear", dash)
        # Not-created filter: only the planned channel.
        planned = self.client.get("/analytics?created=planned&ch=").text
        self.assertIn("Planned One", planned)
        self.assertNotIn(">Focus Daily</a>", planned.split("Channel comparison")[1])
        # Clear brings everything back.
        self.assertIn("<h1>All channels</h1>", self.client.get("/?created=all&ch=").text)

    def test_media_and_schedule_respect_the_filter(self):
        self.assertEqual(self.client.get(f"/schedule?ch={self.planned}").status_code, 200)
        self.assertIn("Nothing scheduled", self.client.get(f"/schedule?ch={self.planned}").text)
        self.assertEqual(self.client.get("/media?created=live").status_code, 200)


if __name__ == "__main__":
    unittest.main()
