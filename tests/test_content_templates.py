"""Tests for the per-niche Excel content templates and upload validation."""
import io
import unittest

from content_templates import NICHES, build_prompt, build_workbook, get_spec, read_workbook
from workflows.focus_habits import FocusHabitsWorkflow


def filled(spec, rows):
    """A workbook whose Content sheet holds the given rows (dicts by column name)."""
    wb = build_workbook(spec)
    names = [name for name, _, _ in spec.columns()]
    for r, row in enumerate(rows, start=2):
        for name, value in row.items():
            wb["Content"].cell(row=r, column=names.index(name) + 1, value=value)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def messages(result):
    return [(e["row"], e["column"], e["message"]) for e in result.errors]


class TestBuild(unittest.TestCase):
    def test_every_niche_builds_all_sheets_with_spec_headers(self):
        for spec in NICHES.values():
            with self.subTest(niche=spec.niche):
                wb = build_workbook(spec)
                self.assertEqual(wb.sheetnames, ["Content", "Guide", "Example", "AI Prompt"])
                header = [c.value for c in wb["Content"][1]]
                self.assertEqual(header, [name for name, _, _ in spec.columns()])

    def test_every_example_is_a_valid_upload(self):
        for spec in NICHES.values():
            with self.subTest(niche=spec.niche):
                result = read_workbook(filled(spec, [spec.example]), spec)
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.videos), 1)

    def test_examples_respect_their_own_limits(self):
        for spec in NICHES.values():
            for name, _, f in spec.columns():
                value = spec.example.get(name, "")
                if f.max_len:
                    self.assertLessEqual(len(value), f.max_len, f"{spec.niche}.{name}")

    def test_prompt_lists_every_column_and_slide_count(self):
        spec = get_spec("science_quiz")
        prompt = build_prompt(spec)
        for name, _, _ in spec.columns():
            self.assertIn(name, prompt)
        self.assertIn("exactly 4 questions", prompt)


class TestRead(unittest.TestCase):
    def setUp(self):
        self.spec = get_spec("focus_habits")
        self.row = dict(self.spec.example)

    def read(self, *rows):
        return read_workbook(filled(self.spec, rows), self.spec)

    def test_focus_habits_upload_feeds_the_workflow(self):
        video = self.read(self.row).videos[0]
        plan = FocusHabitsWorkflow().plan(video["content"])
        self.assertEqual(len(plan.slides), 6)
        self.assertEqual(video["content"]["intro"]["title"], "5 Daily Habits That Ruin Your Focus")
        self.assertEqual(video["youtube"]["tags"][0], "focus")

    def test_blank_rows_are_skipped_and_ids_generated(self):
        second = dict(self.row, video_id="")
        result = read_workbook(filled(self.spec, [self.row, {}, second]), self.spec)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual([v["row"] for v in result.videos], [2, 4])
        self.assertTrue(result.videos[1]["video_id"].startswith("focus_habits-"))

    def test_required_and_length_errors_point_at_the_cell(self):
        row = dict(self.row, intro_title="", habit2_text="x" * 121)
        self.assertEqual(messages(self.read(row)), [
            (2, "intro_title", "required"),
            (2, "habit2_text", "121 characters; the limit is 120"),
        ])

    def test_items_must_be_filled_in_order(self):
        row = dict(self.row, habit3_title="", habit3_text="")
        self.assertIn((2, "habit4", "habit 4 is filled but habit 3 is empty; fill them in order"), messages(self.read(row)))

    def test_too_few_items(self):
        row = {k: v for k, v in self.row.items() if not k.startswith(("habit3", "habit4", "habit5"))}
        self.assertIn((2, None, "2 habits; this template needs at least 3"), messages(self.read(row)))

    def test_publish_at_formats(self):
        result = self.read(dict(self.row, publish_at="2026-10-20 19:00"))
        self.assertEqual(result.videos[0]["publish_at"], "2026-10-20T19:00")
        self.assertIn((2, "publish_at", "'tomorrow' is not a date and time; use YYYY-MM-DD HH:MM"),
                      messages(self.read(dict(self.row, publish_at="tomorrow"))))

    def test_duplicate_video_id(self):
        self.assertIn((3, "video_id", "duplicate video_id 'FH-001'"), messages(self.read(self.row, self.row)))

    def test_description_keeps_line_breaks_written_as_backslash_n(self):
        result = self.read(dict(self.row, youtube_description="Line one\\nLine two"))
        self.assertEqual(result.videos[0]["youtube"]["description"], "Line one\nLine two")

    def test_unknown_and_missing_columns(self):
        spec = self.spec
        wb = build_workbook(spec)
        wb["Content"].cell(row=1, column=1, value="videoid")
        buffer = io.BytesIO()
        wb.save(buffer)
        self.assertEqual(messages(read_workbook(buffer.getvalue(), spec)), [
            (1, "videoid", "unknown column; check the spelling against the template"),
            (1, "video_id", "column is missing"),
        ])

    def test_unused_item_columns_may_be_deleted(self):
        spec = self.spec
        wb = build_workbook(spec)
        sheet = wb["Content"]
        habit6 = [name for name, _, _ in spec.columns()].index("habit6_title") + 1
        sheet.delete_cols(habit6, sheet.max_column - habit6 + 1)
        names = [c.value for c in sheet[1]]
        for name, value in self.row.items():
            sheet.cell(row=2, column=names.index(name) + 1, value=value)
        buffer = io.BytesIO()
        wb.save(buffer)
        self.assertTrue(read_workbook(buffer.getvalue(), spec).ok)

    def test_empty_upload(self):
        self.assertEqual(messages(self.read()), [(None, None, "no videos found; fill the Content sheet from row 2")])


class TestNicheSpecificFields(unittest.TestCase):
    def test_quiz_answer_is_normalised_and_checked(self):
        spec = get_spec("general_quiz")
        ok = read_workbook(filled(spec, [dict(spec.example, q1_correct="b")]), spec)
        slide = ok.videos[0]["content"]["slides"][0]
        self.assertEqual(slide["correct"], "B")
        self.assertEqual(slide["options"], ["Earth", "Mars", "Jupiter", "Venus"])
        bad = read_workbook(filled(spec, [dict(spec.example, q1_correct="E")]), spec)
        self.assertIn((2, "q1_correct", "'E' is not allowed; use one of A, B, C, D"), messages(bad))

    def test_science_quiz_needs_exactly_four_questions(self):
        spec = get_spec("science_quiz")
        self.assertEqual((spec.items.min_count, spec.items.max_count), (4, 4))

    def test_text_position_defaults_alternate(self):
        spec = get_spec("crime_files")
        row = {k: ("" if k.endswith("text_position") else v) for k, v in spec.example.items()}
        slides = read_workbook(filled(spec, [row]), spec).videos[0]["content"]["slides"]
        self.assertEqual([s["textPosition"] for s in slides], ["left", "right", "left", "right"])

    def test_bars_and_image_url(self):
        spec = get_spec("ai_digital_future")
        good = read_workbook(filled(spec, [spec.example]), spec)
        self.assertEqual(good.videos[0]["content"]["slides"][0]["bars"], [55, 70, 48, 82, 64, 91, 76])
        bad = read_workbook(filled(spec, [dict(spec.example, scene1_bars="10,20", scene1_image="photo.jpg")]), spec)
        self.assertEqual(messages(bad), [
            (2, "scene1_image", "must be a full http(s) URL or empty"),
            (2, "scene1_bars", "needs seven numbers from 0 to 100 separated by commas"),
        ])

    def test_not_an_excel_file(self):
        result = read_workbook(b"not a workbook", get_spec("focus_habits"))
        self.assertFalse(result.ok)
        self.assertIn("not a readable .xlsx file", result.errors[0]["message"])


if __name__ == "__main__":
    unittest.main()
