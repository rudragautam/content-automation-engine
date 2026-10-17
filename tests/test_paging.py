"""Tests for list pagination in the content hub."""
import unittest

from tests.test_webapp import HubTestCase
from webapp import db
from webapp.paging import paginate


class TestPaginate(unittest.TestCase):
    def test_slices_and_counts(self):
        p = paginate(list(range(45)), {"page": "2"}, per_page=20)
        self.assertEqual((p.items[0], p.items[-1], p.number, p.pages, p.total, p.start, p.end), (20, 39, 2, 3, 45, 21, 40))

    def test_bad_or_out_of_range_page_is_clamped(self):
        self.assertEqual(paginate(list(range(5)), {"page": "abc"}).number, 1)
        self.assertEqual(paginate(list(range(5)), {"page": "99"}).number, 1)
        self.assertEqual(paginate(list(range(45)), {"page": "99"}, per_page=20).number, 3)
        self.assertEqual(paginate(list(range(45)), {"page": "-3"}, per_page=20).number, 1)

    def test_empty_list_is_falsy_with_one_page(self):
        p = paginate([], {})
        self.assertFalse(p)
        self.assertEqual((p.pages, p.start, p.end), (1, 0, 0))

    def test_links_keep_other_filters_and_anchor(self):
        p = paginate(list(range(100)), {"niche": "crime_files", "status": "", "qpage": "3"}, "qpage", 10, anchor="queue")
        self.assertEqual(p.href(4), "?niche=crime_files&qpage=4#queue")
        self.assertEqual(p.href(1), "?niche=crime_files#queue")

    def test_window_shows_first_last_and_neighbours(self):
        p = paginate(list(range(200)), {"page": "6"}, per_page=10)
        self.assertEqual(p.window(), [1, None, 5, 6, 7, None, 20])
        self.assertEqual(paginate(list(range(30)), {}, per_page=10).window(), [1, 2, 3])


class TestPagedPages(HubTestCase):
    def add_videos(self, n, status="ready"):
        with db.session() as conn:
            conn.executemany(
                "INSERT INTO videos (channel_id, video_ref, title, status, publish_at, content_json, created_at) VALUES (?, ?, ?, ?, ?, '{}', 'now')",
                [(self.focus_channel, f"P{i}", f"Paged video {i:03d}", status, f"2031-01-{1 + i // 10:02d}T{10 + i % 10}:00") for i in range(n)])

    def test_channel_queue_pages(self):
        self.add_videos(45)
        first = self.client.get(f"/channels/{self.focus_channel}").text
        self.assertIn("Paged video 000", first)
        self.assertNotIn("Paged video 030", first)
        self.assertIn('rel="next"', first)
        self.assertIn("qpage=2#queue", first)
        last = self.client.get(f"/channels/{self.focus_channel}?qpage=99").text
        self.assertIn("Paged video 044", last)
        self.assertNotIn("Paged video 000", last)

    def test_content_ready_list_pages_and_shows_total(self):
        self.add_videos(25)
        page1 = self.client.get("/content?niche=focus_habits").text
        self.assertIn("of ", page1)
        self.assertIn("niche=focus_habits&amp;page=2#ready", page1)
        page2 = self.client.get("/content?niche=focus_habits&page=2").text
        self.assertIn("Paged video 024", page2)
        self.assertNotIn("Paged video 000", page2)

    def test_short_lists_have_no_pager(self):
        self.assertNotIn('class="pager"', self.client.get("/audio").text)
        self.assertNotIn('class="pager"', self.client.get("/media").text)


if __name__ == "__main__":
    unittest.main()
