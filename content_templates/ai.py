"""Generate a niche's videos with an AI model, checked by the same rules as an uploaded sheet.

The model gets a JSON schema built from the niche spec (intro + a list of
slides), and its answer is flattened into spreadsheet-style rows and run
through read_rows(). Videos that break a rule are sent back once with the
exact problems to fix; whatever still fails is reported, never queued.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from content_templates.excel import read_rows
from content_templates.specs import VIDEO_FIELDS, Field, NicheSpec

BATCH_SIZE = 5
MAX_VIDEOS = 10

SYSTEM = (
    "You write scripts for short YouTube videos that are rendered from text slides. "
    "You respect every character limit exactly, write in the requested language, "
    "and never invent facts, statistics, quotes, dates or sources."
)

_TYPE = {"text": "STRING", "url": "STRING", "answer": "STRING"}


def _prop(f: Field) -> Dict[str, Any]:
    desc = f.description + (f" At most {f.max_len} characters." if f.max_len else "")
    if f.kind == "bars":
        return {"type": "ARRAY", "items": {"type": "INTEGER"}, "minItems": 7, "maxItems": 7, "description": "Seven whole numbers from 0 to 100."}
    prop = {"type": _TYPE[f.kind], "description": desc}
    if f.choices:
        prop["enum"] = list(f.choices)
    return prop


def _object(fields: List[Field]) -> Dict[str, Any]:
    keys = [f.key for f in fields]
    return {
        "type": "OBJECT",
        "properties": {f.key: _prop(f) for f in fields},
        "required": [f.key for f in fields if f.required or f.choices or f.kind == "bars"],
        "propertyOrdering": keys,
    }


def generated_fields(spec: NicheSpec) -> List[Field]:
    """Slide fields the model fills; images are left to the image library."""
    return [f for f in spec.items.fields if f.kind != "url"]


def response_schema(spec: NicheSpec, count: int) -> Dict[str, Any]:
    youtube = {f.key: f for f in VIDEO_FIELDS if f.key.startswith("youtube_")}
    video = {
        "type": "OBJECT",
        "properties": {
            "youtube_title": _prop(youtube["youtube_title"]),
            "youtube_description": _prop(youtube["youtube_description"]),
            "youtube_tags": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "5 to 12 search tags, lowercase."},
            "intro": _object(list(spec.intro_fields)),
            "slides": {"type": "ARRAY", "items": _object(generated_fields(spec)),
                       "minItems": spec.items.min_count, "maxItems": spec.items.max_count,
                       "description": f"The {spec.items.label}s, in order."},
        },
        "required": ["youtube_title", "youtube_description", "youtube_tags", "intro", "slides"],
        "propertyOrdering": ["youtube_title", "youtube_description", "youtube_tags", "intro", "slides"],
    }
    return {"type": "OBJECT", "properties": {"videos": {"type": "ARRAY", "items": video, "minItems": count, "maxItems": count}}, "required": ["videos"]}


def build_prompt(spec: NicheSpec, topic: str, count: int, channel_name: str = "", instructions: str = "", avoid_titles: List[str] = ()) -> str:
    items = spec.items
    slide_count = f"exactly {items.min_count}" if items.min_count == items.max_count else f"{items.min_count} to {items.max_count}"
    rules = "\n".join(f"- {f.key}: {_prop(f).get('description', '')}" for f in [*spec.intro_fields])
    slide_rules = "\n".join(f"- {f.key}: {_prop(f).get('description', '')}" for f in generated_fields(spec))
    parts = [
        f"Write {count} different videos for the YouTube channel \"{channel_name or spec.name}\" ({spec.name}).",
        f"Topic or theme: {topic}",
        f"Audience and tone: {spec.audience_and_tone}",
        f"Language: {spec.language}",
        f"Each video has an intro slide and {slide_count} {items.label}s.",
        f"Intro fields:\n{rules}",
        f"Fields of each {items.label}:\n{slide_rules}",
        "YouTube fields: a clear, curiosity-driven title without clickbait (max 100 characters); "
        "a 2-4 line description that may end with 3-5 hashtags; 5-12 lowercase search tags.",
        "Rules:\n- Stay within every character limit; spaces count.\n- Every fact must be accurate and checkable.\n"
        "- Each video covers a different angle of the topic.\n- No markdown and no line breaks except inside the description.",
    ]
    if instructions.strip():
        parts.append(f"Extra instructions from the channel owner: {instructions.strip()}")
    if avoid_titles:
        parts.append("These titles are already used on the channel; don't repeat them or their exact angle:\n" + "\n".join(f"- {t}" for t in avoid_titles))
    return "\n\n".join(parts)


def to_row(spec: NicheSpec, video: Dict[str, Any]) -> Dict[str, Any]:
    """One model video -> one spreadsheet-style row (column name -> value)."""
    row = {
        "youtube_title": video.get("youtube_title", ""),
        "youtube_description": video.get("youtube_description", ""),
        "youtube_tags": ", ".join(str(t) for t in video.get("youtube_tags") or []),
    }
    intro = video.get("intro") or {}
    for f in spec.intro_fields:
        row[f"intro_{f.key}"] = intro.get(f.key, "")
    for n, slide in enumerate(video.get("slides") or [], start=1):
        if n > spec.items.max_count:
            break
        for f in spec.items.fields:
            value = slide.get(f.key, "")
            if f.kind == "bars" and isinstance(value, list):
                value = ",".join(str(v) for v in value)
            row[f"{spec.items.prefix}{n}_{f.key}"] = value
    return row


@dataclass
class GenerationResult:
    rows: List[Dict[str, Any]] = field(default_factory=list)  # every generated video, valid or not
    videos: List[Dict[str, Any]] = field(default_factory=list)  # validated, ready to queue
    rejected: List[Dict[str, Any]] = field(default_factory=list)  # {"title", "errors"}


def generate(client, spec: NicheSpec, topic: str, count: int, channel_name: str = "", instructions: str = "",
             avoid_titles: List[str] = ()) -> GenerationResult:
    if not topic.strip():
        raise ValueError("Give a topic or theme.")
    count = max(1, min(int(count), MAX_VIDEOS))
    rows: List[Dict[str, Any]] = []
    while len(rows) < count:
        batch = min(BATCH_SIZE, count - len(rows))
        used = list(avoid_titles) + [r["youtube_title"] for r in rows]
        answer = client.generate_json(build_prompt(spec, topic, batch, channel_name, instructions, used[-60:]), response_schema(spec, batch), system=SYSTEM)
        rows += [to_row(spec, v) for v in (answer.get("videos") or [])[:batch]]
        if not answer.get("videos"):
            break

    result = read_rows(rows, spec, first_row=1)
    failed = _errors_by_row(result)
    if failed:
        fix = [rows[i - 1] for i in failed]
        prompt = (build_prompt(spec, topic, len(fix), channel_name, instructions)
                  + "\n\nThese videos break the rules. Return corrected versions of exactly these videos, in the same order, "
                    "keeping everything that was fine:\n\n"
                  + "\n\n".join(f"Video {k}: {_describe(rows[i - 1])}\nProblems: " + "; ".join(failed[i]) for k, i in enumerate(failed, start=1)))
        answer = client.generate_json(prompt, response_schema(spec, len(fix)), system=SYSTEM)
        for i, video in zip(failed, answer.get("videos") or []):
            rows[i - 1] = to_row(spec, video)
        result = read_rows(rows, spec, first_row=1)

    still = _errors_by_row(result)
    return GenerationResult(
        rows=rows,
        videos=result.videos,
        rejected=[{"title": rows[i - 1].get("youtube_title") or f"Video {i}", "errors": errs} for i, errs in still.items()],
    )


def _errors_by_row(result) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for e in result.errors:
        out.setdefault(e["row"], []).append(f"{e['column']}: {e['message']}" if e["column"] else e["message"])
    return out


def _describe(row: Dict[str, Any]) -> str:
    return "; ".join(f"{k} = {v!r}" for k, v in row.items() if v not in ("", None))
