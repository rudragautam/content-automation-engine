"""The app shell: Channels menu (switching channel), per-channel palettes, the light/dark toggle."""
import re
import unittest

from tests.test_webapp import HubTestCase
from webapp import db, themes, youtube_sync


def palette_of(html):
    return re.search(r'<html lang="en" data-palette="([a-z]+)">', html).group(1)


class TestThemes(unittest.TestCase):
    def test_palettes_and_default(self):
        self.assertEqual(list(themes.PALETTES), ["sunset", "aurora", "blossom", "forest", "midnight", "ember", "graphite"])
        self.assertEqual(themes.palette(None), "ember")
        self.assertEqual(themes.palette("made-up"), "ember")
        self.assertEqual(themes.palette("forest"), "forest")


class TestShell(HubTestCase):
    def setUp(self):
        super().setUp()
        with db.session() as conn:
            self.leo = youtube_sync.add_channel(conn, "Leo Ki Pathshala", "focus_habits", "10:00")
            self.other = youtube_sync.add_channel(conn, "Second Real", "focus_habits", "10:00")
            for cid, yt in ((self.leo, "UCleo"), (self.other, "UCother")):
                conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = ?, is_mock = 0 WHERE id = ?", (yt, cid))

    def test_theme_column_is_added_and_empty_means_ember(self):
        with db.session() as conn:
            self.assertIn("theme", {r["name"] for r in conn.execute("PRAGMA table_info(channels)")})
            self.assertIsNone(conn.execute("SELECT theme FROM channels WHERE id = ?", (self.leo,)).fetchone()[0])
        self.assertEqual(palette_of(self.client.get(f"/channels/{self.leo}").text), "ember")
        self.assertEqual(palette_of(self.client.get("/?created=all&ch=").text), "ember")

    def test_theme_is_saved_per_channel_and_validated(self):
        r = self.client.post(f"/api/channels/{self.leo}/theme", json={"theme": "aurora"})
        self.assertEqual(r.json(), {"theme": "aurora"})
        self.assertEqual(palette_of(self.client.get(f"/channels/{self.leo}").text), "aurora")
        self.assertEqual(palette_of(self.client.get(f"/channels/{self.other}").text), "ember")  # each channel keeps its own
        self.assertEqual(self.client.post(f"/api/channels/{self.leo}/theme", json={"theme": "neon"}).status_code, 400)
        self.assertEqual(self.client.post("/api/channels/99999/theme", json={"theme": "forest"}).status_code, 404)
        self.assertEqual(self.client.post(f"/api/channels/{self.leo}/theme", content=b"not json", headers={"Content-Type": "application/json"}).status_code, 400)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT theme FROM channels WHERE id = ?", (self.leo,)).fetchone()[0], "aurora")

    def test_channels_menu_lists_channels_and_marks_the_active_one(self):
        page = self.client.get(f"/channels/{self.leo}").text
        menu = page.split('id="channels"')[1].split("</aside>")[0]
        self.assertIn("Leo Ki Pathshala", menu)
        self.assertIn("Second Real", menu)
        self.assertIn("All channels", menu)
        # on a channel page, another channel opens that channel's page
        self.assertIn(f'href="/channels/{self.other}"', menu)
        active = re.search(r'<a class="ch on" href="([^"]+)"[^>]*aria-current="true"', menu)
        self.assertEqual(active.group(1), f"/channels/{self.leo}")
        # the active channel shows in the top bar
        self.assertIn('aria-label="Switch channel. Now: Leo Ki Pathshala"', page)

    def test_switching_channel_follows_the_whole_app(self):
        self.client.post(f"/api/channels/{self.leo}/theme", json={"theme": "forest"})
        # pick Leo on a page without the channel filter (Settings): remembered for the next pages
        settings = self.client.get(f"/settings?created=all&ch={self.leo}")
        self.assertEqual(palette_of(settings.text), "forest")
        home = self.client.get("/").text
        self.assertIn("<h1>Leo Ki Pathshala</h1>", home)
        self.assertEqual(palette_of(home), "forest")
        # overview pages keep their own query and swap only the channel
        menu = self.client.get("/analytics?days=7").text.split('id="channels"')[1]
        self.assertIn(f"/analytics?days=7&amp;created=all&amp;ch={self.other}", menu)
        # "All channels" clears it
        self.client.get("/settings?created=all&ch=")
        self.assertIn("<h1>All channels</h1>", self.client.get("/").text)
        self.assertEqual(palette_of(self.client.get("/").text), "ember")

    def test_theme_swatches_and_light_dark_toggle(self):
        page = self.client.get(f"/channels/{self.leo}").text
        self.assertIn(f'data-palette-picker data-channel="{self.leo}"', page)
        self.assertEqual(page.count('data-p="'), 7)
        self.assertIn('aria-pressed="true" aria-label="Ember palette"', page)
        self.assertIn('id="theme-toggle" aria-label="Switch between light and dark"', page)
        self.assertIn('localStorage.getItem("hub-theme")', page)  # chosen before the first paint
        # without an active channel the swatches can't be used
        self.assertIn("Pick a channel to give it a theme", self.client.get("/?created=all&ch=").text)
        # the setup window has the picker too, without the app's navigation
        setup = self.client.get(f"/channels/{self.leo}/setup").text
        self.assertIn(f'data-palette-picker data-channel="{self.leo}"', setup)
        self.assertNotIn('nav class="side', setup)

    def test_static_design_files_are_served(self):
        for path in ("/static/css/tokens.css", "/static/css/components.css", "/static/js/shell.js", "/static/fonts/plus-jakarta-sans-latin.woff2"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        tokens = self.client.get("/static/css/tokens.css").text
        for name in themes.PALETTES:
            if name != "sunset":
                self.assertIn(f'[data-palette="{name}"]', tokens)


if __name__ == "__main__":
    unittest.main()
