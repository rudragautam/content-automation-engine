"""Channel names from Gemini: a name, @handle and angle for a niche.

One niche can have many channels, so Gemini sees the channels the hub already has in
that niche and gives each new one a different angle (audience, format or language).
Nothing is created or renamed until the user picks a suggestion.
"""

import re
from typing import Any, Dict, List, Optional

from content_templates.specs import NICHES
from providers.ai.gemini import Gemini, GeminiError
from webapp import ai_drafts, db
from webapp.queue import ActionError

NAME_LIMIT = 50
ANGLE_LIMIT = 160
COUNT = 6


def suggest(conn, niche: str, idea: str = "", channel_id: Optional[int] = None, client=None) -> List[Dict[str, str]]:
    """Name ideas for a new channel in `niche`, or a new name for `channel_id`."""
    if channel_id:
        row = conn.execute("SELECT niche FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if not row:
            raise ActionError("Channel not found.")
        niche = row["niche"]
    spec = NICHES.get(niche)
    if not spec:
        raise ActionError("Pick a niche.")
    client = client or _client(conn)
    channels = [dict(r) for r in conn.execute("SELECT id, name, handle, niche, angle FROM channels WHERE is_mock = 0")]
    siblings = [c for c in channels if c["niche"] == niche and c["id"] != channel_id]
    current = next((c for c in channels if c["id"] == channel_id), None)
    titles = [r[0] for r in conn.execute(
        "SELECT title FROM videos WHERE channel_id = ? ORDER BY id DESC LIMIT 12", (channel_id,))] if channel_id else []
    idea = re.sub(r"[<>]", "", idea or "").strip()[:300]

    prompt = "\n".join(filter(None, [
        f"Suggest {COUNT} names for a YouTube channel." if not current else
        f"Suggest {COUNT} new names for the YouTube channel now called \"{current['name']}\".",
        f"Niche: {spec.name}. Audience and tone: {spec.audience_and_tone} Video language: {spec.language}.",
        "Its video titles: " + "; ".join(titles) if titles else "",
        f"Its angle: {current['angle']}" if current and current.get("angle") else "",
        "Other channels the owner already runs in this niche (each new name needs a clearly different angle: "
        "audience, format, language or sub-topic):" if siblings else "",
        *[f"- {c['name']}" + (f" — {c['angle']}" if c.get("angle") else "") for c in siblings],
        f"The owner's idea: {idea}" if idea else "",
        "Rules: 2-4 words, memorable, easy to say and spell, and it says what the channel is about. "
        "Hindi-language niches may use Hinglish in Latin letters. No other brands, trademarks, celebrity names, "
        "numbers, emoji or words like 'official'.",
        "Every name must differ from these existing channel names: " + ", ".join(c["name"] for c in channels) if channels else "",
        "handle: the @handle for the name, lowercase letters and digits only (dots allowed), 3-30 characters.",
        "angle: one sentence on who it is for and what makes it different.",
        "No < or > characters.",
    ]))
    try:
        answer = client.generate_json(prompt, _schema(), temperature=1.0)
    except GeminiError as e:
        raise ActionError(str(e))
    return clean(answer, {c["name"].casefold() for c in channels})


def _client(conn) -> Gemini:
    key, model = ai_drafts.api_key(), db.get_setting(conn, "gemini_model")
    if not key or not model:
        raise ActionError("Add your Gemini API key in Settings first.")
    return Gemini(key, model)


def _schema() -> Dict[str, Any]:
    item = {"type": "OBJECT", "properties": {
        "name": {"type": "STRING", "description": f"The channel name, up to {NAME_LIMIT} characters."},
        "handle": {"type": "STRING", "description": "@handle without the @."},
        "angle": {"type": "STRING", "description": "One sentence: who it is for and what makes it different."},
    }, "required": ["name", "handle", "angle"], "propertyOrdering": ["name", "handle", "angle"]}
    return {"type": "OBJECT", "properties": {"names": {"type": "ARRAY", "items": item, "minItems": COUNT, "maxItems": COUNT}},
            "required": ["names"]}


def clean(answer: Dict[str, Any], taken) -> List[Dict[str, str]]:
    out, seen = [], set(taken)
    for item in answer.get("names") or []:
        name = re.sub(r"\s+", " ", re.sub(r"[<>]", "", str(item.get("name") or ""))).strip()[:NAME_LIMIT]
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        out.append({"name": name, "handle": handle(item.get("handle") or name),
                    "angle": re.sub(r"[<>]", "", str(item.get("angle") or "")).strip()[:ANGLE_LIMIT]})
    return out


def handle(value: str) -> str:
    """'@Leo Ki Pathshala!' -> '@leokipathshala' (YouTube handles: letters, digits, . _ -; 3-30 long)."""
    text = re.sub(r"[^a-z0-9._-]", "", str(value).lower().lstrip("@"))[:30].strip("._-")
    return "@" + text if len(text) >= 3 else ""


def rename(conn, channel_id: int, name: str, new_handle: str, angle: str) -> None:
    """Rename a channel that isn't on YouTube yet. Connected channels take their name from YouTube."""
    row = conn.execute("SELECT connection, is_mock FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not row:
        raise ActionError("Channel not found.")
    if row["connection"] == "connected":
        raise ActionError("This channel is on YouTube, so its name comes from there. Change it in YouTube Studio; the next sync brings it here.")
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        raise ActionError("Give the channel a name.")
    conn.execute("UPDATE channels SET name = ?, handle = ?, angle = ? WHERE id = ?",
                 (name[:100], handle(new_handle) if new_handle.strip() else "", angle.strip()[:ANGLE_LIMIT], channel_id))
