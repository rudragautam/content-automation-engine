"""Tests for AI content generation and the Gemini client, with fakes (no network)."""
import json
import unittest
from unittest import mock

import httpx

from content_templates import ai, get_spec
from content_templates.excel import read_workbook, workbook_with_rows
from providers.ai import gemini


def model_video(spec, **overrides):
    """A valid model answer for one video, built from the niche example."""
    ex = spec.example
    slides = []
    for n in range(1, spec.items.max_count + 1):
        values = {f.key: ex.get(f"{spec.items.prefix}{n}_{f.key}", "") for f in ai.generated_fields(spec)}
        if not any(values.values()):
            break
        if "bars" in values:
            values["bars"] = [int(x) for x in values["bars"].split(",")]
        slides.append(values)
    video = {
        "youtube_title": ex["youtube_title"],
        "youtube_description": ex["youtube_description"],
        "youtube_tags": [t.strip() for t in ex["youtube_tags"].split(",")],
        "intro": {f.key: ex.get(f"intro_{f.key}", "") for f in spec.intro_fields},
        "slides": slides,
    }
    video.update(overrides)
    return video


class FakeClient:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def generate_json(self, prompt, schema, system=""):
        self.prompts.append((prompt, schema))
        return self.answers.pop(0)


class TestSchemaAndRows(unittest.TestCase):
    def test_schema_follows_the_spec(self):
        spec = get_spec("ai_digital_future")
        schema = ai.response_schema(spec, 3)
        videos = schema["properties"]["videos"]
        self.assertEqual((videos["minItems"], videos["maxItems"]), (3, 3))
        slide = videos["items"]["properties"]["slides"]
        self.assertEqual((slide["minItems"], slide["maxItems"]), (4, 4))
        props = slide["items"]["properties"]
        self.assertNotIn("image", props)
        self.assertEqual(props["text_position"]["enum"], ["left", "right", "center"])
        self.assertEqual(props["bars"]["type"], "ARRAY")
        self.assertIn("At most 80 characters", props["title"]["description"])

    def test_quiz_answer_is_an_enum(self):
        props = ai.response_schema(get_spec("general_quiz"), 1)["properties"]["videos"]["items"]["properties"]["slides"]["items"]["properties"]
        self.assertEqual(props["correct"]["enum"], ["A", "B", "C", "D"])

    def test_every_niche_example_round_trips_as_a_model_answer(self):
        from content_templates import NICHES
        for spec in NICHES.values():
            with self.subTest(niche=spec.niche):
                result = ai.read_rows([ai.to_row(spec, model_video(spec))], spec, first_row=1)
                self.assertEqual(result.errors, [])

    def test_rows_export_to_an_uploadable_workbook(self):
        spec = get_spec("focus_habits")
        data = workbook_with_rows(spec, [ai.to_row(spec, model_video(spec))])
        self.assertTrue(read_workbook(data, spec).ok)


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.spec = get_spec("focus_habits")

    def test_batches_of_five(self):
        good = model_video(self.spec)
        client = FakeClient([{"videos": [dict(good, youtube_title=f"T{i}") for i in range(5)]},
                             {"videos": [dict(good, youtube_title=f"U{i}") for i in range(2)]}])
        result = ai.generate(client, self.spec, "focus", 7)
        self.assertEqual(len(result.videos), 7)
        self.assertEqual([p[1]["properties"]["videos"]["maxItems"] for p in client.prompts], [5, 2])
        self.assertIn("T0", client.prompts[1][0])  # second batch is told not to repeat the first

    def test_broken_video_is_repaired_once(self):
        good = model_video(self.spec)
        long_text = dict(good["slides"][0], text="x" * 150)
        broken = dict(good, slides=[long_text] + good["slides"][1:])
        client = FakeClient([{"videos": [good, broken]}, {"videos": [good]}])
        result = ai.generate(client, self.spec, "focus", 2)
        self.assertEqual((len(result.videos), result.rejected), (2, []))
        self.assertIn("habit1_text: 150 characters; the limit is 120", client.prompts[1][0])

    def test_still_broken_video_is_rejected_not_queued(self):
        good = model_video(self.spec)
        broken = dict(good, intro=dict(good["intro"], title=""))
        client = FakeClient([{"videos": [good, broken]}, {"videos": [broken]}])
        result = ai.generate(client, self.spec, "focus", 2)
        self.assertEqual(len(result.videos), 1)
        self.assertEqual(result.rejected[0]["errors"], ["intro_title: required"])
        self.assertEqual(len(result.rows), 2)

    def test_prompt_carries_context(self):
        prompt = ai.build_prompt(self.spec, "morning routines", 3, "Focus Daily", "Use Indian examples", ["Old title"])
        for text in ("morning routines", "Focus Daily", "Use Indian examples", "Old title", "3 to 8 habits", "At most 120 characters"):
            self.assertIn(text, prompt)

    def test_empty_topic(self):
        with self.assertRaises(ValueError):
            ai.generate(FakeClient([]), self.spec, "  ", 2)


def transport(handler):
    return httpx.MockTransport(handler)


class TestGeminiClient(unittest.TestCase):
    def test_key_goes_in_header_and_models_are_filtered(self):
        seen = {}

        def handler(request):
            seen["key"] = request.headers.get("x-goog-api-key")
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            ]})

        models = gemini.Gemini("secret-key", transport=transport(handler)).list_models()
        self.assertEqual(models, [{"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"}])
        self.assertEqual(seen["key"], "secret-key")
        self.assertNotIn("secret-key", seen["url"])

    def test_generate_json_sends_schema_and_parses_reply(self):
        sent = {}

        def handler(request):
            sent.update(json.loads(request.content))
            sent["path"] = request.url.path
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": '{"videos": []}'}]}, "finishReason": "STOP"}]})

        client = gemini.Gemini("k", "gemini-2.5-flash", transport=transport(handler))
        self.assertEqual(client.generate_json("hi", {"type": "OBJECT"}, system="sys"), {"videos": []})
        self.assertEqual(sent["path"], "/v1beta/models/gemini-2.5-flash:generateContent")
        self.assertEqual(sent["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(sent["systemInstruction"]["parts"][0]["text"], "sys")

    def test_errors_are_explained(self):
        cases = [
            (httpx.Response(400, json={"error": {"message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}), "isn't valid"),
            (httpx.Response(404, json={"error": {"message": "models/x is not found"}}), "isn't available"),
            (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), "refused"),
            (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"vid'}]}, "finishReason": "MAX_TOKENS"}]}), "cut off"),
            (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}), "valid JSON"),
        ]
        for response, text in cases:
            with self.subTest(text=text):
                client = gemini.Gemini("k", "m", transport=transport(lambda r, res=response: res))
                with self.assertRaises(gemini.GeminiError) as ctx:
                    client.generate_json("p", {})
                self.assertIn(text, str(ctx.exception))

    def test_rate_limit_is_retried(self):
        replies = [httpx.Response(429, json={"error": {"message": "slow down"}}), httpx.Response(200, json={"models": []})]
        with mock.patch.object(gemini, "RETRY_WAITS", (0, 0)):
            self.assertEqual(gemini.Gemini("k", transport=transport(lambda r: replies.pop(0))).list_models(), [])

    def test_default_model_is_newest_stable_flash(self):
        ids = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-3-flash-preview"]
        self.assertEqual(gemini.pick_default_model([{"id": i, "name": i} for i in ids]), "gemini-2.5-flash")
        self.assertEqual(gemini.pick_default_model([{"id": "gemini-x-flash-preview", "name": ""}]), "gemini-x-flash-preview")
        self.assertIsNone(gemini.pick_default_model([]))

    def test_missing_key(self):
        with self.assertRaises(gemini.GeminiError):
            gemini.Gemini("")


if __name__ == "__main__":
    unittest.main()
