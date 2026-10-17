"""Settings: channels grouped by the Google account they sign in with, planned channels, niche changes."""
import base64
import json
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from publishing import youtube as yt
from tests.test_webapp import HubTestCase
from webapp import db, youtube_sync


def id_token(claims):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


class TestAccountEmail(unittest.TestCase):
    def test_email_comes_from_the_id_token(self):
        self.assertEqual(yt.account_email(mock.Mock(id_token=id_token({"email": "owner@gmail.com"}))), "owner@gmail.com")

    def test_missing_or_broken_token_gives_nothing(self):
        self.assertEqual(yt.account_email(mock.Mock(id_token=None)), "")
        self.assertEqual(yt.account_email(mock.Mock(id_token="a.!!!.c")), "")
        self.assertEqual(yt.account_email(object()), "")

    def test_sign_in_asks_for_the_email_but_stored_sign_ins_need_only_youtube(self):
        self.assertTrue(set(yt.SCOPES) < set(yt.LOGIN_SCOPES))
        self.assertIn("https://www.googleapis.com/auth/userinfo.email", yt.LOGIN_SCOPES)
        self.assertNotIn("openid", yt.SCOPES)


class TestSettingsPage(HubTestCase):
    def setUp(self):
        super().setUp()
        youtube_sync.save_client_file(
            b'{"web": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "s", '
            b'"auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", '
            b'"redirect_uris": ["http://testserver/oauth/callback"]}}')
        with db.session() as conn:
            conn.execute("DELETE FROM channels WHERE is_mock = 1")
            self.old = youtube_sync.add_channel(conn, "Old Connect", "focus_habits", "19:00")
            conn.execute("UPDATE channels SET connection = 'connected', youtube_channel_id = 'UCold' WHERE id = ?", (self.old,))
            self.planned = youtube_sync.add_channel(conn, "Case Closed", "crime_files", "19:00", "@caseclosed")

    def sign_in(self, found, email):
        r = self.client.post("/settings/connect", data={"niche": "science_quiz", "slots": "19:00"}, follow_redirects=False)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        creds = mock.Mock(refresh_token="r", id_token=id_token({"email": email}))
        with mock.patch("publishing.youtube.exchange_code", return_value=creds), \
                mock.patch("publishing.youtube.build_services", return_value=(None, None)), \
                mock.patch("publishing.youtube.my_channel", return_value=found), \
                mock.patch("publishing.youtube.save_credentials"):
            return self.client.get(f"/oauth/callback?state={state}&code=x")

    def test_connect_records_the_google_account(self):
        self.sign_in({"id": "UCsci", "title": "Science Sawaal", "handle": "@sci", "subscribers": 1}, "owner@gmail.com")
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT google_account FROM channels WHERE youtube_channel_id = 'UCsci'").fetchone()[0], "owner@gmail.com")

    def test_channels_are_grouped_by_account_then_planned(self):
        self.sign_in({"id": "UCsci", "title": "Science Sawaal", "handle": "@sci", "subscribers": 1}, "owner@gmail.com")
        page = self.client.get("/settings").text
        for text in ("There's no single logged-in account", "owner@gmail.com", "Google account not recorded",
                     "Planned · not on YouTube yet", "Create a channel", f'href="/oauth/start?channel={self.planned}"', "@caseclosed"):
            self.assertIn(text, page)
        # account group, then the unknown-account group, then planned channels
        self.assertLess(page.index("owner@gmail.com"), page.index("Google account not recorded"))
        self.assertLess(page.index("Old Connect"), page.index("Case Closed"))
        self.assertLess(page.index("Science Sawaal"), page.index("Old Connect"))

    def test_opened_at_another_address_says_where_sign_in_works(self):
        youtube_sync.save_client_file(
            b'{"web": {"client_id": "abc.apps.googleusercontent.com", "client_secret": "s", '
            b'"redirect_uris": ["http://127.0.0.1:8000/oauth/callback"]}}')
        page = self.client.get("/settings").text
        self.assertIn("Sign-ins only work at", page)
        self.assertIn('href="http://127.0.0.1:8000/settings"', page)
        self.assertNotIn("doesn't list the hub's redirect URI", page)

    def test_change_niche(self):
        r = self.client.post(f"/settings/channels/{self.old}/niche", data={"niche": "science_quiz"})
        self.assertIn("Niche changed to", r.text)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT niche FROM channels WHERE id = ?", (self.old,)).fetchone()[0], "science_quiz")
        self.assertIn("Pick a niche", self.client.post(f"/settings/channels/{self.old}/niche", data={"niche": "nope"}).text)

    def test_niche_stays_while_content_waits_to_render(self):
        with db.session() as conn:
            conn.execute("INSERT INTO videos (channel_id, video_ref, title, status, content_json, created_at) VALUES (?, 'v1', 't', 'ready', '{}', 'now')", (self.old,))
        r = self.client.post(f"/settings/channels/{self.old}/niche", data={"niche": "science_quiz"})
        self.assertIn("waiting to render", r.text)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT niche FROM channels WHERE id = ?", (self.old,)).fetchone()[0], "focus_habits")


if __name__ == "__main__":
    unittest.main()
