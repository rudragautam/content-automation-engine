"""Channel names from Gemini: suggestions per niche, adding and renaming planned channels."""
import unittest
from unittest import mock

from tests.test_webapp import HubTestCase
from webapp import ai_drafts, channel_names, db, youtube_sync


class FakeNamer:
    def __init__(self, names):
        self.names, self.prompt = names, ""

    def generate_json(self, prompt, schema, system="", temperature=0.9):
        self.prompt, self.schema = prompt, schema
        return {"names": self.names}


class TestCleaning(unittest.TestCase):
    def test_handle(self):
        self.assertEqual(channel_names.handle("@Leo Ki Pathshala!"), "@leokipathshala")
        self.assertEqual(channel_names.handle("ab"), "")
        self.assertEqual(len(channel_names.handle("x" * 80)), 31)

    def test_clean_drops_taken_and_duplicate_names(self):
        out = channel_names.clean({"names": [
            {"name": "Focus Daily", "handle": "focusdaily", "angle": "a"},
            {"name": "  Study   <Sprint> ", "handle": "", "angle": "For <b>exam</b> weeks"},
            {"name": "study sprint", "handle": "x", "angle": ""},
            {"name": "", "handle": "x", "angle": ""},
        ]}, {"focus daily"})
        self.assertEqual(out, [{"name": "Study Sprint", "handle": "@studysprint", "angle": "For bexam/b weeks"}])


class TestNamesInHub(HubTestCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            self.leo = youtube_sync.add_channel(conn, "Leo Ki Pathshala", "focus_habits", "19:00", "@leo", "Hinglish habits for kids")
            conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = 'UCleo' WHERE id = ?", (self.leo,))
            self.other = youtube_sync.add_channel(conn, "Crime Desk", "crime_files", "19:00")

    def test_new_channel_names_know_the_niche_siblings(self):
        fake = FakeNamer([{"name": "Leo Ki Pathshala", "handle": "x", "angle": ""},
                          {"name": "Deep Work Desi", "handle": "deepworkdesi", "angle": "Hindi focus tips for office workers"}])
        with db.session() as conn:
            names = channel_names.suggest(conn, "focus_habits", "for adults", client=fake)
        self.assertEqual([n["name"] for n in names], ["Deep Work Desi"])  # an existing name is dropped
        self.assertIn("Leo Ki Pathshala — Hinglish habits for kids", fake.prompt)  # same-niche channel and its angle
        self.assertNotIn("Crime Desk —", fake.prompt)  # other niches aren't siblings
        self.assertIn("Crime Desk", fake.prompt)  # but their names are still taken
        self.assertIn("for adults", fake.prompt)

    def test_names_for_an_existing_channel_use_its_niche_and_titles(self):
        with db.session() as conn:
            conn.execute("INSERT INTO videos (channel_id, video_ref, title, status, created_at) VALUES (?, 'v1', 'Brush with Leo', 'published', 'now')", (self.leo,))
        fake = FakeNamer([{"name": "Leo Learns", "handle": "leolearns", "angle": "x"}])
        with db.session() as conn:
            channel_names.suggest(conn, "", channel_id=self.leo, client=fake)
        self.assertIn('now called "Leo Ki Pathshala"', fake.prompt)
        self.assertIn("Brush with Leo", fake.prompt)
        self.assertIn("Its angle: Hinglish habits for kids", fake.prompt)

    def test_route_needs_a_key_and_a_niche(self):
        self.assertIn("Gemini API key", self.client.post("/api/channel-names", data={"niche": "focus_habits"}).json()["error"])
        with mock.patch("webapp.channel_names._client", return_value=FakeNamer([])):
            self.assertIn("Pick a niche", self.client.post("/api/channel-names", data={"niche": "nope"}).json()["error"])

    def test_add_planned_channel_with_handle_and_angle(self):
        r = self.client.post("/settings/channels", data={"name": "Deep Work Desi", "niche": "focus_habits", "slots": "19:00",
                                                         "handle": "Deep Work Desi", "angle": "Hindi focus tips for office workers"})
        self.assertEqual(r.status_code, 200)
        with db.session() as conn:
            row = conn.execute("SELECT handle, angle FROM channels WHERE name = 'Deep Work Desi'").fetchone()
        self.assertEqual((row["handle"], row["angle"]), ("@deepworkdesi", "Hindi focus tips for office workers"))
        page = self.client.get("/settings").text
        self.assertIn("Suggest names", page)
        self.assertIn("Hindi focus tips for office workers", page)

    def test_rename_planned_but_not_connected_channels(self):
        r = self.client.post(f"/channels/{self.other}/setup/name", data={"name": "Case Closed Hindi", "handle": "caseclosedhindi", "angle": "True crime in Hindi"})
        self.assertIn("Renamed to", r.text)
        with db.session() as conn:
            row = conn.execute("SELECT name, handle, angle FROM channels WHERE id = ?", (self.other,)).fetchone()
        self.assertEqual(tuple(row), ("Case Closed Hindi", "@caseclosedhindi", "True crime in Hindi"))
        r = self.client.post(f"/channels/{self.leo}/setup/name", data={"name": "New"})
        self.assertIn("Change it in YouTube Studio", r.text)

    def test_settings_lists_connected_channels_first(self):
        page = self.client.get("/settings").text
        table = page[page.index("<tbody>", page.index('id="channels"')):]
        self.assertLess(table.index("Leo Ki Pathshala"), table.index("Crime Desk"))  # alphabetically it would be last

    def test_setup_window_offers_rename_or_copy(self):
        planned = self.client.get(f"/channels/{self.other}/setup").text
        self.assertIn('data-mode="rename"', planned)
        self.assertIn("Name &amp; handle", planned)

    def test_drafts_follow_the_channel_angle(self):
        with db.session() as conn:
            draft = conn.execute(
                "INSERT INTO drafts (niche, channel_id, topic, count, instructions, model, status, created_at) VALUES ('focus_habits', ?, 'sleep', 1, 'short', 'm', 'generating', 'now')",
                (self.leo,)).lastrowid
        with mock.patch("webapp.ai_drafts.generate", side_effect=ValueError("stop")) as gen:
            ai_drafts.run_draft(draft, client=object())
        self.assertEqual(gen.call_args[0][5], "This channel's angle: Hinglish habits for kids\nshort")


if __name__ == "__main__":
    unittest.main()
