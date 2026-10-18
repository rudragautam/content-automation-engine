"""AI Optimizer: the Gemini schema, the hub's checks on the answer, and retries, with a fake model."""
import unittest

from providers.ai.gemini import GeminiError, GeminiQuotaError
from publishing import youtube as yt
from webapp import optimizer
from webapp.optimizer import OptimizerError, Target, check_package, generate_package


def target(**overrides):
    values = dict(channel_name="Leo Ki Pathshala", handle="@leo_ki_pathshala", language="hi", made_for_kids=True, is_short=True,
                  title="Haath Dhona | Leo Ki Pathshala #shorts", description="", tags=[],
                  content="Topic: hand washing. 5 steps", channel_titles=["Sach Bolna Kyu Zaroori Hai? | Leo Ki Pathshala #shorts"])
    values.update(overrides)
    return Target(**values)


def answer(**overrides):
    a = {
        "titles": ["हाथ धोना क्यों ज़रूरी है? | Good Habits for Kids", "खाने से पहले हाथ धोओ | Leo Ki Pathshala", "साफ़ हाथ, स्वस्थ बच्चे"],
        "description": "बच्चों के लिए हाथ धोने के 5 आसान स्टेप।\nbacchon ke liye haath dhone ki aadat\nComment karo aapko kaisa laga!",
        "hashtags": ["#GoodHabits", "#KidsLearning", "#हाथ_धोना"],
        "tags": ["good habits for kids", "haath dhona", "hand wash for kids in hindi", "बच्चों की आदतें", "kids hindi", "leo ki pathshala"],
        "why": ["'haath dhona' is what parents search", "Comment section ideas"],
        "shorts": {"hook": "Kya aapke haath sach mein saaf hain?", "on_screen_text": "5 STEP", "loop_ending": "Ends on the first step's image",
                   "cta": "Comment karo aur bell dabao!"},
    }
    a.update(overrides)
    return a


class FakeModel:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def generate_json(self, prompt, schema, system="", temperature=0.9):
        self.prompts.append((prompt, schema))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class TestSchema(unittest.TestCase):
    def test_shorts_fields_only_for_shorts(self):
        short = optimizer.package_schema(True)
        self.assertIn("shorts", short["required"])
        self.assertEqual(short["properties"]["titles"]["minItems"], 3)
        self.assertEqual(short["properties"]["titles"]["maxItems"], 3)
        self.assertNotIn("shorts", optimizer.package_schema(False)["properties"])

    def test_prompt_follows_language_and_made_for_kids(self):
        p = optimizer.build_prompt(target())
        self.assertIn("Devanagari", p)
        self.assertIn("Roman script only", p)
        self.assertIn("Never ask viewers to comment", p)
        self.assertIn("Agla part dekho", p)
        self.assertIn("first 3 seconds", p)
        plain = optimizer.build_prompt(target(language="en", made_for_kids=False, is_short=False))
        self.assertIn("in English", plain)
        self.assertNotIn("Devanagari", plain)
        self.assertNotIn("MADE FOR KIDS", plain)
        self.assertNotIn("SHORTS", plain)

    def test_prompt_passes_footer_defaults_and_problems(self):
        p = optimizer.build_prompt(target(footer="Subscribe karo!\n#Leo", default_tags=["leo"]), problems=["No usable title"])
        self.assertIn("Subscribe karo! / #Leo", p)
        self.assertIn("don't repeat them: leo", p)
        self.assertIn("- No usable title", p)


class TestCheckPackage(unittest.TestCase):
    def test_made_for_kids_answer_is_cleaned(self):
        pkg, warnings, problems = check_package(answer(), target())
        self.assertEqual(problems, [])
        self.assertEqual(len(pkg["titles"]), 3)
        self.assertNotIn("Comment", pkg["description"])
        self.assertTrue(pkg["description"].endswith("#GoodHabits #KidsLearning"))
        self.assertEqual(pkg["shorts"]["cta"], "Agla part dekho 👉")
        self.assertEqual(pkg["why"], ["'haath dhona' is what parents search"])
        self.assertNotIn("बच्चों की आदतें", pkg["tags"])  # tags stay Roman
        self.assertTrue(any("Made for Kids" in w for w in warnings))
        self.assertTrue(any("Devanagari" in w for w in warnings))

    def test_comment_cta_kept_when_not_for_kids(self):
        pkg, _, problems = check_package(answer(), target(made_for_kids=False))
        self.assertEqual(problems, [])
        self.assertIn("Comment karo", pkg["description"])
        self.assertIn("Comment karo", pkg["shorts"]["cta"])

    def test_hindi_channel_needs_devanagari_titles(self):
        _, _, problems = check_package(answer(titles=["Haath Dhona", "Clean Hands", "Wash Up"]), target())
        self.assertTrue(any(p.startswith("No usable title in Devanagari script") for p in problems))
        pkg, _, problems = check_package(answer(titles=["Clean Hands for Kids", "Wash Up", "Soap Time"]), target(language="en"))
        self.assertEqual(problems, [])
        self.assertEqual(len(pkg["titles"]), 3)

    def test_long_title_is_cut_on_a_word(self):
        long = "हाथ " * 40
        pkg, warnings, _ = check_package(answer(titles=[long, "दूसरा", "तीसरा"]), target())
        self.assertLessEqual(len(pkg["titles"][0]), yt.TITLE_LIMIT)
        self.assertFalse(pkg["titles"][0].endswith(" "))
        self.assertTrue(any("shortened" in w for w in warnings))

    def test_tags_fit_with_the_channel_defaults(self):
        defaults = ["leo ki pathshala", "kids"]
        many = [f"search phrase number {i}" for i in range(40)]
        pkg, warnings, _ = check_package(answer(tags=many + ["Leo Ki Pathshala"]), target(default_tags=defaults))
        self.assertLessEqual(yt.tags_length(pkg["tags"] + defaults), yt.TAGS_LIMIT)
        self.assertNotIn("Leo Ki Pathshala", pkg["tags"])  # already a default tag
        self.assertTrue(any("500-character" in w for w in warnings))

    def test_description_fits_bytes_with_the_footer(self):
        footer = "चैनल को सब्सक्राइब करें " * 20
        pkg, warnings, _ = check_package(answer(description="बच्चों के लिए " * 600), target(footer=footer))
        total = yt.description_bytes(pkg["description"]) + yt.description_bytes(footer) + 2
        self.assertLessEqual(total, yt.DESCRIPTION_LIMIT)
        self.assertTrue(pkg["description"].endswith("#GoodHabits #KidsLearning"))
        self.assertTrue(any("5,000-byte" in w for w in warnings))

    def test_hashtags_from_the_text_move_and_footer_ones_are_skipped(self):
        a = answer(description="Line one\n#Extra #GoodHabits", hashtags=["GoodHabits", "#Leo"])
        pkg, _, _ = check_package(a, target(footer="Subscribe\n#Leo", made_for_kids=False))
        self.assertEqual(pkg["hashtags"], ["#GoodHabits", "#Extra"])
        self.assertEqual(pkg["description_body"], "Line one")

    def test_short_needs_a_hook(self):
        _, _, problems = check_package(answer(shorts={"hook": "", "on_screen_text": "", "loop_ending": "", "cta": ""}), target())
        self.assertIn("The Short has no hook line for the first 3 seconds.", problems)
        pkg, _, problems = check_package(answer(), target(is_short=False))
        self.assertIsNone(pkg["shorts"])

    def test_broken_answers_are_problems(self):
        self.assertEqual(check_package(["not", "an", "object"], target())[2], ["The answer wasn't a JSON object."])
        _, _, problems = check_package({}, target())
        self.assertIn("The description is empty.", problems)
        self.assertTrue(any("usable tags" in p for p in problems))

    def test_angle_brackets_never_reach_youtube(self):
        pkg, _, _ = check_package(answer(titles=["हाथ <धोना>", "दूसरा", "तीसरा"], description="a <b> c"), target())
        self.assertNotIn("<", pkg["titles"][0] + pkg["description"])


class TestGenerate(unittest.TestCase):
    def test_bad_answer_is_retried_with_its_problems(self):
        model = FakeModel([answer(titles=["Only Roman", "Also Roman", "Roman"]), answer()])
        pkg, _ = generate_package(model, target())
        self.assertEqual(len(model.prompts), 2)
        self.assertIn("No usable title in Devanagari script", model.prompts[1][0])
        self.assertEqual(len(pkg["titles"]), 3)

    def test_invalid_json_is_retried_then_fails_cleanly(self):
        model = FakeModel([GeminiError("Gemini's answer wasn't valid JSON. Try again."), answer()])
        self.assertTrue(generate_package(model, target())[0]["titles"])
        model = FakeModel([GeminiError("Gemini's answer wasn't valid JSON. Try again.")] * 2)
        with self.assertRaises(OptimizerError) as e:
            generate_package(model, target())
        self.assertIn("keeps its current title", str(e.exception))

    def test_no_quota_is_not_retried(self):
        model = FakeModel([GeminiQuotaError("free-tier limit is 0"), answer()])
        with self.assertRaises(OptimizerError):
            generate_package(model, target())
        self.assertEqual(len(model.prompts), 1)


if __name__ == "__main__":
    unittest.main()
