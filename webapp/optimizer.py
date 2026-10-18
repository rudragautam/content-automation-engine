"""AI Optimizer: Gemini suggests a better title, description, tags and, for Shorts, a hook package.

One generate_json call per video, sent only a short summary (current metadata, what the
video covers, the channel's own titles and its best performers), never raw data. The
answer is checked here before anyone sees it: YouTube's limits counted with the channel's
footer and default tags, the channel's language (Hindi = Devanagari titles, Roman tags
and hashtags), and for Made for Kids videos no comment, bell or notification CTAs.
A bad answer is retried once with the problems listed; after that the suggestion fails
with a readable error and the video keeps its metadata. Nothing is applied without the
user's approval (webapp.metadata_apply).
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from content_templates import NICHES, get_spec
from providers.ai.gemini import Gemini, GeminiError, GeminiQuotaError
from publishing import youtube as yt
from webapp import channel_setup, db, metadata_apply, timeutil
from webapp.queue import ActionError

logger = logging.getLogger(__name__)

SHORT_MAX_SECONDS = 180
ATTEMPTS = 2
HOOK_LIMIT, ON_SCREEN_LIMIT, LOOP_LIMIT, CTA_LIMIT = 80, 50, 200, 60
MAX_HASHTAGS = 5
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Comments and notifications are off on Made for Kids videos, so these CTAs can't work there.
KIDS_BLOCKED_CTA = re.compile(
    r"comment|कमेंट|कॉमेंट|टिप्पणी|reply|रिप्लाई|\bbell\b|घंटी|notification|नोटिफिकेशन|🔔|"
    r"neeche\s+likh|नीचे\s+लिख|batao\s+neeche|niche\s+batao", re.IGNORECASE)
SAFE_CTA = {"hi": "Agla part dekho 👉", "en": "Watch the next one 👉"}
# Advice that can't be followed on a Made for Kids video: these features are switched off there.
KIDS_BLOCKED_ADVICE = re.compile(KIDS_BLOCKED_CTA.pattern + r"|end[\s-]?screen|\bcards?\b|community post|pinned|live chat|personali[sz]ed ads",
                                 re.IGNORECASE)
NOT_ENOUGH = "Not enough data yet"

_run_lock = threading.Lock()  # one optimizer thread talks to Gemini at a time; the free tier has low rate limits


class OptimizerError(Exception):
    """Gemini couldn't produce a usable suggestion; the message is fit to show the user."""


@dataclass
class Target:
    """Everything the prompt and the checks need to know about one video."""
    channel_name: str
    language: str                      # channel_setup.LANGUAGES code
    made_for_kids: bool
    is_short: bool
    title: str
    description: str
    tags: List[str]
    handle: str = ""
    angle: str = ""
    niche_hint: str = ""
    content: str = ""                  # what the video covers, in one or two lines
    channel_titles: List[str] = field(default_factory=list)
    best_titles: List[Tuple[str, int]] = field(default_factory=list)
    footer: str = ""
    default_tags: List[str] = field(default_factory=list)
    analysis: bool = False             # a video on YouTube: also ask for a score, reasons, actions and ideas
    findings: List[str] = field(default_factory=list)          # this video's numbers (optimizer_checks.video_findings)
    channel_findings: List[str] = field(default_factory=list)  # the channel's main findings

    @property
    def too_little_data(self) -> bool:
        return any(f.startswith(NOT_ENOUGH) for f in self.findings)


# ---------- prompt and schema ----------

DEVANAGARI_TITLE_RULE = ("Title words in Hindi, Devanagari script, even where the channel's current titles are in Roman script. "
                         "Only the channel name, #shorts and one or two English search words may stay in Roman.")


def package_schema(is_short: bool, language: str = "", analysis: bool = False) -> Dict[str, Any]:
    string = {"type": "STRING"}
    titles = f"Three different title options, best first, each at most {yt.TITLE_LIMIT} characters."
    props: Dict[str, Any] = {
        "titles": {"type": "ARRAY", "items": string, "minItems": 3, "maxItems": 3,
                   "description": titles + (" " + DEVANAGARI_TITLE_RULE if language == "hi" else "")},
        "description": {"type": "STRING", "description": "The description without hashtags: 3-6 short lines, search phrases in the first line."},
        "hashtags": {"type": "ARRAY", "items": string, "minItems": 3, "maxItems": MAX_HASHTAGS, "description": "Hashtags starting with #, no spaces."},
        "tags": {"type": "ARRAY", "items": string, "minItems": 8, "maxItems": 15, "description": "Search tags, 1-4 words each, the phrases viewers type."},
        "why": {"type": "ARRAY", "items": string, "minItems": 2, "maxItems": 4,
                "description": "Short reasons for the changes, each naming the keyword or number it rests on."},
    }
    order = ["titles", "description", "hashtags", "tags", "why"]
    if is_short:
        props["shorts"] = {"type": "OBJECT", "properties": {
            "hook": {"type": "STRING", "description": f"The line said or shown in the first 3 seconds, at most {HOOK_LIMIT} characters."},
            "on_screen_text": {"type": "STRING", "description": f"Big text on screen at the start, at most {ON_SCREEN_LIMIT} characters."},
            "loop_ending": {"type": "STRING", "description": "How the last second leads back into the first, so the Short replays."},
            "cta": {"type": "STRING", "description": f"A closing call to action, at most {CTA_LIMIT} characters."},
        }, "required": ["hook", "on_screen_text", "loop_ending", "cta"],
            "propertyOrdering": ["hook", "on_screen_text", "loop_ending", "cta"]}
        order.append("shorts")
    if analysis:
        props.update({
            "health_score": {"type": "INTEGER", "description": "0-100: how well this video's metadata and numbers set it up for reach."},
            "summary": {"type": "STRING", "description": "2-3 short lines: what holds this video back and the single most useful fix."},
            "reasons": {"type": "ARRAY", "maxItems": 4, "items": {"type": "OBJECT", "properties": {
                "reason": string, "number": {"type": "STRING", "description": "The number from the findings this reason rests on, e.g. 4% search."}},
                "required": ["reason", "number"], "propertyOrdering": ["reason", "number"]},
                "description": "Reasons for low reach, each tied to a number from the findings. Empty if the findings say not enough data."},
            "actions": {"type": "ARRAY", "items": string, "minItems": 5, "maxItems": 7, "description": "Concrete actions, most impact first."},
            "ideas": {"type": "ARRAY", "minItems": 3, "maxItems": 3, "items": {"type": "OBJECT", "properties": {
                "title": string, "why": {"type": "STRING", "description": "Which existing video or number it builds on."}},
                "required": ["title", "why"], "propertyOrdering": ["title", "why"]},
                "description": "Follow-up video ideas built on what already worked on this channel."},
        })
        order += ["health_score", "summary", "reasons", "actions", "ideas"]
    return {"type": "OBJECT", "properties": props, "required": order, "propertyOrdering": order}


def build_prompt(t: Target, problems: List[str] = ()) -> str:
    language = channel_setup.LANGUAGES.get(t.language, t.language)
    if t.language == "hi":
        script = [
            "LANGUAGE: Hindi audience.",
            f"- {DEVANAGARI_TITLE_RULE} Example pattern: \"हाथ धोना सीखो | Channel Name #shorts\".",
            "- Description: short Devanagari lines, plus one Roman-script Hinglish line with the search phrases parents type (e.g. bacchon ke liye achhi aadatein).",
            "- Tags and hashtags in Roman script only: Hinglish and English phrases parents type, e.g. good habits for kids in hindi, bacchon ki kahani.",
        ]
    else:
        script = [f"LANGUAGE: write titles, description, tags and hashtags in {language}."]
    kids = [
        "MADE FOR KIDS: this video is set as made for kids, so comments and notifications are off.",
        "- Never ask viewers to comment, reply, write below, press the bell or turn on notifications.",
        f"- The CTA must work without comments, e.g. \"{SAFE_CTA.get(t.language, SAFE_CTA['en'])}\" or watching the next part.",
        "- Write the description for parents: what the child learns. No links, no personal data, nothing scary.",
    ] if t.made_for_kids else []
    shorts = [
        "SHORTS: this is a vertical Short. Give a hook for the first 3 seconds, big on-screen text, a loop ending and a CTA.",
        "- The hook states the problem or question at once; no greetings, no channel intro.",
    ] if t.is_short else []
    analysis = [
        "NUMBERS FROM YOUTUBE ANALYTICS for this video (the only facts you may base reasons on):",
        *[f"- {f}" for f in t.findings],
        "THE CHANNEL'S MAIN FINDINGS:" if t.channel_findings else "",
        *[f"- {f}" for f in t.channel_findings],
        "ANALYSIS RULES:",
        "- Every reason names the number it rests on, copied from the lines above. Never invent a number or a cause.",
        "- If the numbers say \"Not enough data yet\", return no reasons and say so in the summary; still improve the metadata.",
        "- Actions are things the creator can do now or in the next videos; the video itself can't be re-edited, only its metadata.",
        "- Ideas build on this channel's best videos or topics, for the same audience.",
        "- No advice about comments, notifications, end screens, cards or community posts: they're off on Made for Kids videos." if t.made_for_kids else "",
    ] if t.analysis else []
    return "\n".join(filter(None, [
        f"Improve the YouTube title, description and tags of one video on the channel \"{t.channel_name}\"{' (' + t.handle + ')' if t.handle else ''},"
        " so more of the right viewers find it in search and in their feeds.",
        "WHAT THE CHANNEL ACTUALLY IS (most important):",
        f"- Its angle: {t.angle}" if t.angle else "",
        "- Its recent titles: " + "; ".join(t.channel_titles) if t.channel_titles else "",
        "- Its best videos so far (views): " + "; ".join(f"{title} ({views})" for title, views in t.best_titles) if t.best_titles else "",
        f"- Hint only, ignore where it disagrees with the above: the hub files it under {t.niche_hint}." if t.niche_hint else "",
        "THIS VIDEO NOW:",
        f"- Title: {t.title}",
        f"- Description: {t.description[:400]}" if t.description else "- Description: (empty)",
        f"- Tags: {', '.join(t.tags)}" if t.tags else "- Tags: (none)",
        f"- What it covers: {t.content[:600]}" if t.content else "",
        *script, *kids, *shorts, *analysis,
        "RULES:",
        f"- Titles: aim for 40-70 characters, never over {yt.TITLE_LIMIT}. Put the main search phrase first. Keep the channel's naming pattern"
        " if its titles share one (e.g. \"| Channel Name\")" + (", but follow the LANGUAGE rule for the script" if t.language == "hi" else "") +
        ". No clickbait, no ALL CAPS, no < or > characters.",
        "- Don't repeat the exact title of another video on the channel.",
        "- Description: no hashtags inside it; they go in the hashtags field.",
        "- The channel adds this footer to every description by itself, so don't repeat it: " + t.footer.replace("\n", " / ") if t.footer else "",
        "- These tags are added to every video by themselves, so don't repeat them: " + ", ".join(t.default_tags) if t.default_tags else "",
        "- No made-up facts, numbers, links or promises of results.",
        "YOUR PREVIOUS ANSWER HAD THESE PROBLEMS; fix all of them:\n" + "\n".join(f"- {p}" for p in problems) if problems else "",
    ]))


# ---------- checking the answer ----------

def check_package(answer: Any, t: Target) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """(package, warnings, problems). Problems make the answer unusable; warnings say what the hub repaired."""
    warnings: List[str] = []
    problems: List[str] = []
    if not isinstance(answer, dict):
        return {}, warnings, ["The answer wasn't a JSON object."]

    titles, dropped_script = [], 0
    for raw in answer.get("titles") or []:
        title = yt.clean_text(" ".join(str(raw).split()))
        if not title or title.lower() in {x.lower() for x in titles}:
            continue
        if t.language == "hi" and not DEVANAGARI.search(title):
            dropped_script += 1
            continue
        if len(title) > yt.TITLE_LIMIT:
            title = _cut_words(title, yt.TITLE_LIMIT)
            warnings.append(f"A title was over {yt.TITLE_LIMIT} characters and was shortened.")
        titles.append(title)
    if dropped_script:
        warnings.append(f"{dropped_script} title option{'s' if dropped_script > 1 else ''} not in Devanagari {'were' if dropped_script > 1 else 'was'} left out.")
    if not titles:
        problems.append("No usable title in Devanagari script: write the title words in Devanagari, not Roman Hinglish." if t.language == "hi" else "No usable title.")

    lines, hashtags_in_text, kids_lines = [], [], 0
    for line in str(answer.get("description") or "").replace("\r\n", "\n").split("\n"):
        line = line.strip()
        words = line.split()
        if words and all(w.startswith("#") for w in words):
            hashtags_in_text += words
            continue
        if t.made_for_kids and KIDS_BLOCKED_CTA.search(line):
            kids_lines += 1
            continue
        lines.append(line)
    if kids_lines:
        warnings.append(f"Removed {kids_lines} description line{'s' if kids_lines > 1 else ''} asking for comments or notifications (off on Made for Kids videos).")
    body = yt.clean_text(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)))
    if not body:
        problems.append("The description is empty.")

    footer_tags = {h.lower() for h in re.findall(r"#\w+", t.footer)}
    hashtags, dropped_hashtags = [], 0
    for raw in list(answer.get("hashtags") or []) + hashtags_in_text:
        tag = "#" + re.sub(r"[^\w]", "", str(raw))
        if len(tag) < 2 or tag.lower() in footer_tags or tag.lower() in {h.lower() for h in hashtags}:
            continue
        if t.language == "hi" and not tag.isascii():
            dropped_hashtags += 1
            continue
        hashtags.append(tag)
    if dropped_hashtags:
        warnings.append("Hashtags not in Roman script were left out.")
    if len(hashtags) > MAX_HASHTAGS:
        hashtags = hashtags[:MAX_HASHTAGS]

    own_defaults = {d.lower() for d in t.default_tags}
    tags, dropped_tags = [], 0
    for raw in answer.get("tags") or []:
        tag = re.sub(r"[<>#,]", "", " ".join(str(raw).split())).strip()
        if not tag or tag.lower() in own_defaults or tag.lower() in {x.lower() for x in tags}:
            continue
        if t.language == "hi" and DEVANAGARI.search(tag):
            dropped_tags += 1
            continue
        tags.append(tag)
    if dropped_tags:
        warnings.append(f"{dropped_tags} tag{'s' if dropped_tags > 1 else ''} in Devanagari {'were' if dropped_tags > 1 else 'was'} left out (tags stay in Roman script).")
    # Leave room for the channel's default tags, which the upload adds after these.
    budget = yt.TAGS_LIMIT - yt.tags_length(t.default_tags) - (1 if t.default_tags else 0)
    fitted = yt.fit_tags(tags, budget)
    if len(fitted) < len(tags):
        warnings.append(f"{len(tags) - len(fitted)} tag{'s' if len(tags) - len(fitted) > 1 else ''} left out to stay within YouTube's {yt.TAGS_LIMIT}-character limit.")
    tags = fitted
    if len(tags) < 3:
        problems.append(f"Only {len(tags)} usable tags; give 8-15" + (" in Roman script." if t.language == "hi" else "."))

    # The footer and its blank line are added at upload; the description must still fit with them.
    budget = yt.DESCRIPTION_LIMIT - (yt.description_bytes(t.footer) + 2 if t.footer else 0)
    tail = ("\n\n" + " ".join(hashtags)) if hashtags else ""
    if yt.description_bytes(body + tail) > budget:
        body = yt.fit_description(body, max(budget - yt.description_bytes(tail), 0))
        warnings.append(f"The description was shortened to fit YouTube's {yt.DESCRIPTION_LIMIT:,}-byte limit.")
    description = body + tail

    shorts = None
    if t.is_short:
        raw = answer.get("shorts") if isinstance(answer.get("shorts"), dict) else {}
        shorts = {
            "hook": _cut_words(" ".join(str(raw.get("hook") or "").split()), HOOK_LIMIT),
            "on_screen_text": _cut_words(" ".join(str(raw.get("on_screen_text") or "").split()), ON_SCREEN_LIMIT),
            "loop_ending": _cut_words(" ".join(str(raw.get("loop_ending") or "").split()), LOOP_LIMIT),
            "cta": _cut_words(" ".join(str(raw.get("cta") or "").split()), CTA_LIMIT),
        }
        if t.made_for_kids:
            if KIDS_BLOCKED_CTA.search(shorts["cta"]):
                shorts["cta"] = SAFE_CTA.get(t.language, SAFE_CTA["en"])
                warnings.append("The CTA asked for comments or notifications (off on Made for Kids videos), so a safe one is used.")
            for key in ("hook", "on_screen_text", "loop_ending"):
                if KIDS_BLOCKED_CTA.search(shorts[key]):
                    shorts[key] = ""
                    warnings.append(f"The {key.replace('_', ' ')} asked for comments or notifications and was left out.")
        if not shorts["hook"]:
            problems.append("The Short has no hook line for the first 3 seconds.")
        if not shorts["cta"]:
            shorts["cta"] = SAFE_CTA.get(t.language, SAFE_CTA["en"])

    why = [_cut_words(" ".join(str(w).split()), 220) for w in (answer.get("why") or []) if str(w).strip()][:4]
    if t.made_for_kids:
        why = [w for w in why if not KIDS_BLOCKED_CTA.search(w)]

    package = {"titles": titles, "description": description, "description_body": body, "hashtags": hashtags,
               "tags": tags, "why": why, "shorts": shorts}
    if t.analysis:
        package.update(_check_analysis(answer, t, warnings, problems))
    return package, warnings, problems


def _check_analysis(answer: Dict[str, Any], t: Target, warnings: List[str], problems: List[str]) -> Dict[str, Any]:
    blocked = KIDS_BLOCKED_ADVICE if t.made_for_kids else None
    try:
        score = max(0, min(100, int(answer.get("health_score"))))
    except (TypeError, ValueError):
        score = None
        problems.append("health_score must be a whole number from 0 to 100.")
    summary = _cut_words(" ".join(str(answer.get("summary") or "").split()), 400)
    if not summary:
        problems.append("The summary is empty.")

    reasons, untied = [], 0
    for r in answer.get("reasons") or []:
        if not isinstance(r, dict):
            continue
        reason, number = " ".join(str(r.get("reason") or "").split()), " ".join(str(r.get("number") or "").split())
        if not reason:
            continue
        if not re.search(r"\d", number + reason):
            untied += 1
            continue
        if blocked and blocked.search(reason):
            continue
        reasons.append({"reason": _cut_words(reason, 240), "number": _cut_words(number, 80)})
    if untied:
        warnings.append(f"Left out {untied} reason{'s' if untied > 1 else ''} not tied to a number.")
    if t.too_little_data:
        if reasons:
            warnings.append("This video has too few views to say why; Gemini's guesses were left out.")
        reasons = []
    elif not reasons and t.findings:
        problems.append("Give at least one reason, each tied to a number from the findings.")

    actions, dropped = [], 0
    for a in answer.get("actions") or []:
        a = _cut_words(" ".join(str(a).split()), 240)
        if not a or a.lower() in {x.lower() for x in actions}:
            continue
        if blocked and blocked.search(a):
            dropped += 1
            continue
        actions.append(a)
    if dropped:
        warnings.append(f"Left out {dropped} action{'s' if dropped > 1 else ''} using features that are off on Made for Kids videos.")
    actions = actions[:7]
    if len(actions) < 3:
        problems.append(f"Only {len(actions)} usable actions; give 5-7.")

    ideas = []
    for i in answer.get("ideas") or []:
        if isinstance(i, dict) and str(i.get("title") or "").strip() and not (blocked and blocked.search(str(i.get("title")) + str(i.get("why")))):
            ideas.append({"title": _cut_words(" ".join(str(i["title"]).split()), 120), "why": _cut_words(" ".join(str(i.get("why") or "").split()), 240)})
    return {"health_score": score, "summary": summary, "reasons": reasons, "actions": actions, "ideas": ideas[:3],
            "too_little_data": t.too_little_data}


def _cut_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(" |,-–:")


def generate_package(client, t: Target) -> Tuple[Dict[str, Any], List[str]]:
    """Ask Gemini, check the answer and retry once with the problems; (package, warnings)."""
    problems: List[str] = []
    last_error = ""
    for _ in range(ATTEMPTS):
        try:
            answer = client.generate_json(build_prompt(t, problems), package_schema(t.is_short, t.language, t.analysis), temperature=0.7)
        except GeminiQuotaError as e:
            raise OptimizerError(str(e))  # waiting won't help
        except GeminiError as e:
            last_error, problems = str(e), []  # the client already retried network errors and rate limits
            continue
        package, warnings, problems = check_package(answer, t)
        if not problems:
            return package, warnings
        last_error = "Gemini's suggestion didn't pass the hub's checks: " + " ".join(problems)
    raise OptimizerError(f"{last_error} The video keeps its current title, description and tags; try again.")


# ---------- building a target ----------

def _channel_context(conn, channel_id: int, exclude_video: Optional[int] = None) -> Dict[str, Any]:
    c = conn.execute("SELECT name, handle, angle, niche FROM channels WHERE id = ?", (channel_id,)).fetchone()
    prefs = channel_setup.defaults(conn, channel_id)
    titles = [r[0] for r in conn.execute(
        "SELECT title FROM videos WHERE channel_id = ? AND id != ? ORDER BY COALESCE(publish_at, created_at) DESC LIMIT 12",
        (channel_id, exclude_video or 0))]
    best = [(r[0], r[1]) for r in conn.execute(
        "SELECT title, views FROM videos WHERE channel_id = ? AND status = 'published' AND views > 0 ORDER BY views DESC LIMIT 3", (channel_id,))]
    spec = NICHES.get(c["niche"])
    return {
        "channel_name": c["name"], "handle": c["handle"] or "", "angle": c["angle"] or "",
        "niche_hint": f"{spec.name} ({spec.audience_and_tone})" if spec else "",
        "language": prefs["language"], "made_for_kids": bool(prefs["made_for_kids"]),
        "footer": prefs["description_footer"], "default_tags": list(prefs["default_tags"]),
        "channel_titles": titles, "best_titles": best,
    }


def _summary(intro: Dict[str, Any], slides: List[Dict[str, Any]]) -> str:
    parts = [str(v) for v in intro.values() if isinstance(v, str) and v.strip()]
    for s in slides:
        first = next((str(v) for v in s.values() if isinstance(v, str) and v.strip() and not str(v).startswith("http")), "")
        if first:
            parts.append(first)
    return "; ".join(parts)


def target_for_draft_row(conn, draft_id: int, row_number: int) -> Target:
    d = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    rows = json.loads(d["rows_json"] or "[]")
    row = rows[row_number - 1]
    spec = get_spec(d["niche"])
    intro = {f.key: row.get(f"intro_{f.key}", "") for f in spec.intro_fields}
    slides = [{f.key: row.get(f"{spec.items.prefix}{n}_{f.key}", "") for f in spec.items.fields} for n in range(1, spec.items.max_count + 1)]
    ctx = _channel_context(conn, d["channel_id"])
    return Target(title=row.get("youtube_title", "") or "", description=row.get("youtube_description", "") or "",
                  tags=metadata_apply.parse_tags(row.get("youtube_tags", "") or ""), is_short=spec.aspect_ratio == "9:16",
                  content=f"Topic: {d['topic']}. " + _summary(intro, [s for s in slides if any(s.values())]), **ctx)


def target_for_video(conn, video_id: int) -> Target:
    v = conn.execute("SELECT v.*, c.niche FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (video_id,)).fetchone()
    content = json.loads(v["content_json"] or "{}")
    spec = NICHES.get(v["niche"])
    short = v["duration_s"] <= SHORT_MAX_SECONDS if v["duration_s"] else bool(spec and spec.aspect_ratio == "9:16")
    ctx = _channel_context(conn, v["channel_id"], video_id)
    return Target(title=v["title"], description=v["description"], tags=metadata_apply.parse_tags(v["tags"]), is_short=short,
                  content=_summary(content.get("intro") or {}, content.get("slides") or []), **ctx)


# ---------- suggestions: start, run, read ----------

def _model(conn) -> str:
    from webapp import ai_drafts

    if not ai_drafts.api_key():
        raise ActionError("Add your Gemini API key in Settings first.")
    model = db.get_setting(conn, "gemini_model")
    if not model:
        raise ActionError("Pick a Gemini model in Settings first.")
    return model


def _insert(conn, channel_id: int, model: str, t: Target, video_id: Optional[int] = None, draft_id: Optional[int] = None,
            draft_row: Optional[int] = None) -> int:
    return conn.execute(
        "INSERT INTO video_suggestions (channel_id, video_id, draft_id, draft_row, model, status, language, made_for_kids, is_short, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (channel_id, video_id, draft_id, draft_row, model, "generating", t.language, int(t.made_for_kids), int(t.is_short),
         timeutil.fmt(timeutil.now_local()))).lastrowid


def start_for_draft(conn, draft_id: int, row_number: Optional[int] = None) -> List[int]:
    """Suggestions for one row of a ready draft, or every row; runs in the background."""
    d = conn.execute("SELECT channel_id, status, rows_json FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if not d:
        raise ActionError("Draft not found.")
    if d["status"] != "ready":
        raise ActionError("Only a draft that's ready for review can get suggestions; queued videos get them in the channel's queue.")
    count = len(json.loads(d["rows_json"] or "[]"))
    rows = [row_number] if row_number else list(range(1, count + 1))
    if not rows or any(not 1 <= r <= count for r in rows):
        raise ActionError("That video isn't in this draft.")
    busy = {r[0] for r in conn.execute("SELECT draft_row FROM video_suggestions WHERE draft_id = ? AND status = 'generating'", (draft_id,))}
    rows = [r for r in rows if r not in busy]
    if not rows:
        raise ActionError("Gemini is already writing suggestions for this.")
    model = _model(conn)
    ids = [_insert(conn, d["channel_id"], model, target_for_draft_row(conn, draft_id, r), draft_id=draft_id, draft_row=r) for r in rows]
    conn.commit()
    threading.Thread(target=run, args=(ids,), daemon=True).start()
    return ids


def target_for_remote(conn, s) -> Target:
    """A video on YouTube, from what the channel analysis read and found (context_json)."""
    ctx = json.loads(s["context_json"])
    live = ctx["live"]
    channel = _channel_context(conn, s["channel_id"], s["video_id"])
    # Nothing is added at upload any more: the description and tags are sent exactly as shown.
    channel.update(footer="", default_tags=[], made_for_kids=bool(live.get("made_for_kids")))
    v = conn.execute("SELECT content_json FROM videos WHERE id = ?", (s["video_id"],)).fetchone()
    content = json.loads(v["content_json"]) if v and v["content_json"] else {}
    return Target(title=live["title"], description=live["description"], tags=list(live["tags"]), is_short=bool(s["is_short"]),
                  content=_summary(content.get("intro") or {}, content.get("slides") or []), analysis=True,
                  findings=ctx.get("findings", []), channel_findings=ctx.get("channel_findings", []), **channel)


def insert_remote(conn, audit_id: int, channel_id: int, model: str, video_id: int, live: Dict[str, Any], is_short: bool,
                  findings: List[str], channel_findings: List[str]) -> int:
    language = channel_setup.defaults(conn, channel_id)["language"]
    context = {"live": live, "findings": findings, "channel_findings": channel_findings}
    return conn.execute(
        "INSERT INTO video_suggestions (channel_id, video_id, audit_id, model, status, language, made_for_kids, is_short, context_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (channel_id, video_id, audit_id, model, "generating", language, int(bool(live.get("made_for_kids"))), int(is_short),
         json.dumps(context, ensure_ascii=False), timeutil.fmt(timeutil.now_local()))).lastrowid


def start_for_video(conn, video_id: int) -> int:
    v = conn.execute("SELECT channel_id, status, youtube_video_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not v:
        raise ActionError("Video not found.")
    if v["youtube_video_id"] or v["status"] not in metadata_apply.LOCAL_STATUSES:
        raise ActionError("This video is already on YouTube; run the channel analysis to get suggestions for it.")
    if conn.execute("SELECT 1 FROM video_suggestions WHERE video_id = ? AND status = 'generating'", (video_id,)).fetchone():
        raise ActionError("Gemini is already writing suggestions for this video.")
    model = _model(conn)
    sid = _insert(conn, v["channel_id"], model, target_for_video(conn, video_id), video_id=video_id)
    conn.commit()
    threading.Thread(target=run, args=([sid],), daemon=True).start()
    return sid


def live_made_for_kids(conn, channel_id: int) -> Optional[bool]:
    """The channel's Made for Kids setting on YouTube (1 quota unit), or None if it can't be read."""
    from webapp import youtube_sync

    c = conn.execute("SELECT connection, is_mock FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not c or c["is_mock"] or c["connection"] != "connected":
        return None
    try:
        youtube, _ = youtube_sync._services(conn, channel_id)
        value = yt.channel_setup(youtube).get("made_for_kids")
        youtube_sync._add_quota(conn, 1)
        return None if value is None else bool(value)
    except Exception as e:  # a read for a safety hint must never stop the suggestions
        logger.info("Couldn't read Made for Kids for channel %s: %s", channel_id, type(e).__name__)
        return None


def run(ids: List[int], client=None, live_kids=live_made_for_kids) -> None:
    """Write each suggestion in turn: one Gemini call per video."""
    from webapp import ai_drafts

    with _run_lock:
        conn = db.connect()
        own = None

        def _own():
            nonlocal own
            own = Gemini(ai_drafts.api_key(), s["model"])
            return own

        try:
            kids_by_channel: Dict[int, Optional[bool]] = {}
            for sid in ids:
                s = conn.execute("SELECT * FROM video_suggestions WHERE id = ?", (sid,)).fetchone()
                if not s or s["status"] != "generating":
                    continue
                try:
                    if s["context_json"]:  # a video on YouTube: its own live Made for Kids setting is already known
                        package, warnings = generate_package(client or own or _own(), target_for_remote(conn, s))
                        conn.execute("UPDATE video_suggestions SET status = 'ready', package_json = ?, warnings_json = ?, error = NULL WHERE id = ?",
                                     (json.dumps(package, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), sid))
                        conn.commit()
                        continue
                    t = target_for_draft_row(conn, s["draft_id"], s["draft_row"]) if s["draft_id"] else target_for_video(conn, s["video_id"])
                    if s["channel_id"] not in kids_by_channel:
                        kids_by_channel[s["channel_id"]] = live_kids(conn, s["channel_id"])
                    live = kids_by_channel[s["channel_id"]]
                    early: List[str] = []
                    if live and not t.made_for_kids:
                        early.append("YouTube marks this channel as Made for Kids, but its upload defaults in the hub say No. "
                                     "The suggestions follow the kids' rules; set Made for Kids in Setup → Upload defaults before uploading.")
                    t.made_for_kids = t.made_for_kids or bool(live)  # the stricter of the two; never changes either setting
                    if client is None and own is None:
                        own = Gemini(ai_drafts.api_key(), s["model"])
                    package, warnings = generate_package(client or own, t)
                    conn.execute("UPDATE video_suggestions SET status = 'ready', made_for_kids = ?, package_json = ?, warnings_json = ?, error = NULL WHERE id = ?",
                                 (int(t.made_for_kids), json.dumps(package, ensure_ascii=False), json.dumps(early + warnings, ensure_ascii=False), sid))
                except (OptimizerError, GeminiError, ActionError) as e:
                    conn.execute("UPDATE video_suggestions SET status = 'failed', error = ? WHERE id = ?", (str(e)[:500], sid))
                except Exception as e:
                    logger.exception("Suggestion %s failed", sid)
                    conn.execute("UPDATE video_suggestions SET status = 'failed', error = ? WHERE id = ?", (f"Suggestions failed: {type(e).__name__}"[:500], sid))
                conn.commit()
        finally:
            if own is not None:
                own.close()
            conn.commit()
            conn.close()


def get(conn, suggestion_id: int):
    s = conn.execute("SELECT * FROM video_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not s:
        raise ActionError("Suggestion not found.")
    return s


def view(conn, s) -> Dict[str, Any]:
    """A suggestion with its parsed package, the target's current metadata and a preview of the first option."""
    out = dict(s)
    out["package"] = json.loads(s["package_json"]) if s["package_json"] else None
    out["warnings"] = json.loads(s["warnings_json"] or "[]")
    out["blocked"] = metadata_apply.editable_problem(conn, s)
    out["remote"] = metadata_apply.is_remote(s)
    if out["remote"]:
        ctx = json.loads(s["context_json"])
        out["findings"] = ctx.get("findings", [])
        out["youtube_video_id"] = ctx["live"]["id"]
        out["video_title"] = ctx["live"]["title"]
        out["recent"] = metadata_apply.recent_change(conn, ctx["live"]["id"])
    if out["blocked"]:
        return out
    out["current"] = metadata_apply.current(conn, s)
    if out["package"] and out["package"]["titles"]:
        p = out["package"]
        out["preview"] = metadata_apply.preview(conn, s, p["titles"][0], p["description"], p["tags"])
    elif s["status"] == "applied" and s["applied_json"]:
        a = json.loads(s["applied_json"])
        out["preview"] = metadata_apply.preview(conn, s, a["title"], a["description"], a["tags"])
    if s["before_json"]:
        out["before"] = json.loads(s["before_json"])
    return out


def restart(conn, suggestion_id: int) -> None:
    """Ask Gemini again for a suggestion that's ready or failed (not one already applied)."""
    s = get(conn, suggestion_id)
    if s["status"] not in ("ready", "failed"):
        raise ActionError("Roll back the applied change first, then ask again." if s["status"] == "applied" else "Gemini is already writing this one.")
    model = _model(conn)
    conn.execute("UPDATE video_suggestions SET status = 'generating', model = ?, error = NULL WHERE id = ?", (model, suggestion_id))
    conn.commit()
    threading.Thread(target=run, args=([suggestion_id],), daemon=True).start()


def for_draft(conn, draft_id: int) -> Dict[int, Dict[str, Any]]:
    """The latest suggestion for each row of a draft."""
    out: Dict[int, Dict[str, Any]] = {}
    for s in conn.execute("SELECT * FROM video_suggestions WHERE draft_id = ? ORDER BY id", (draft_id,)):
        out[s["draft_row"]] = s
    return {row: view(conn, s) for row, s in out.items()}


def for_video(conn, video_id: int) -> Optional[Dict[str, Any]]:
    s = conn.execute("SELECT * FROM video_suggestions WHERE video_id = ? ORDER BY id DESC LIMIT 1", (video_id,)).fetchone()
    return view(conn, s) if s else None
