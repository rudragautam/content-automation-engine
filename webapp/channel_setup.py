"""Channel setup: what the hub can change on a YouTube channel, and the upload defaults it uses.

Channel name, @handle and profile picture are Studio-only; everything else that the
YouTube Data API allows lives here. Nothing changes on YouTube until a section is saved.
"""

import io
import json
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

from content_templates.specs import NICHES
from publishing import youtube as yt
from webapp import db
from webapp.queue import ActionError

CATEGORIES = {  # YouTube video categories that suit these channels
    "27": "Education", "28": "Science & Technology", "24": "Entertainment", "22": "People & Blogs",
    "25": "News & Politics", "26": "Howto & Style", "1": "Film & Animation", "10": "Music",
}
LANGUAGES = {"en": "English", "hi": "Hindi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "mr": "Marathi",
             "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu", "es": "Spanish"}
COUNTRIES = {"IN": "India", "US": "United States", "GB": "United Kingdom", "CA": "Canada", "AU": "Australia",
             "AE": "United Arab Emirates", "SG": "Singapore", "NP": "Nepal", "BD": "Bangladesh", "LK": "Sri Lanka"}
PRIVACY = {"public": "Public", "unlisted": "Unlisted", "private": "Private"}

BANNER_MIN = (2048, 1152)
BANNER_MAX_BYTES = 6 * 1024 * 1024
WATERMARK_MIN = (150, 150)
WATERMARK_MAX_BYTES = 1024 * 1024
IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif"}


# ---------- upload defaults (stored in the hub) ----------

def defaults(conn, channel_id: int) -> Dict[str, Any]:
    """What every upload from this channel uses. Falls back to what suits the niche."""
    row = conn.execute("SELECT niche, setup_json FROM channels WHERE id = ?", (channel_id,)).fetchone()
    from webapp.youtube_sync import CATEGORY

    spec = NICHES.get(row["niche"])
    base = {
        "category_id": CATEGORY.get(row["niche"], "27"),
        "language": "hi" if spec and spec.language.startswith("Hindi") else "en",
        "made_for_kids": False,
        "synthetic_media": True,
        "description_footer": "",
        "default_tags": [],
        "playlist_id": "",
    }
    saved = json.loads(row["setup_json"] or "{}")
    return {**base, **{k: v for k, v in saved.items() if k in base}}


def save_defaults(conn, channel_id: int, form: Dict[str, str]) -> Dict[str, Any]:
    current = defaults(conn, channel_id)
    category, language = form.get("category_id", ""), form.get("language", "")
    if category not in CATEGORIES:
        raise ActionError("Pick a category from the list.")
    if language not in LANGUAGES:
        raise ActionError("Pick a language from the list.")
    footer = form.get("description_footer", "").strip()
    if len(footer) > 1000:
        raise ActionError(f"The description footer is {len(footer)} characters; keep it under 1,000.")
    tags = [t.strip() for t in form.get("default_tags", "").split(",") if t.strip()]
    if sum(len(t) + 1 for t in tags) > 200:
        raise ActionError("Default tags are too long; keep them under 200 characters so each video's own tags still fit.")
    current.update({
        "category_id": category, "language": language,
        "made_for_kids": form.get("made_for_kids") == "yes",
        "synthetic_media": form.get("synthetic_media") != "no",
        "description_footer": footer, "default_tags": tags,
    })
    _store(conn, channel_id, current)
    return current


def set_upload_playlist(conn, channel_id: int, playlist_id: str) -> None:
    current = defaults(conn, channel_id)
    current["playlist_id"] = playlist_id.strip()
    _store(conn, channel_id, current)


def _store(conn, channel_id: int, values: Dict[str, Any]) -> None:
    conn.execute("UPDATE channels SET setup_json = ? WHERE id = ?", (json.dumps(values, ensure_ascii=False), channel_id))


# ---------- reading what is live on YouTube ----------

def load(conn, channel_id: int, services=None) -> Dict[str, Any]:
    """The live channel settings plus its playlists and recent videos (3 quota units)."""
    youtube = _youtube(conn, channel_id, services)
    live = yt.channel_setup(youtube)
    playlists = yt.list_playlists(youtube)
    videos = yt.recent_videos(youtube, live["uploads_playlist"], 25) if live["uploads_playlist"] else []
    _quota(conn, 3 + (1 if videos else 0))
    return {"live": live, "playlists": playlists, "videos": [v for v in videos if v["privacy"] == "public"]}


# ---------- writing to YouTube ----------

def save_about(conn, channel_id: int, form: Dict[str, str], services=None) -> None:
    description = form.get("description", "").replace("\r\n", "\n").strip()
    if len(description) > yt.ABOUT_LIMIT:
        raise ActionError(f"The description is {len(description)} characters; YouTube allows {yt.ABOUT_LIMIT}.")
    if re.search(r"[<>]", description):
        raise ActionError("YouTube doesn't allow < or > in the channel description.")
    keywords = yt.format_keywords([k for k in re.split(r"[,\n]", form.get("keywords", "")) if k.strip()])
    if len(keywords) > yt.KEYWORDS_LIMIT:
        raise ActionError(f"Keywords take {len(keywords)} characters; YouTube allows {yt.KEYWORDS_LIMIT}. Remove a few.")
    country, language = form.get("country", ""), form.get("language", "")
    if country and country not in COUNTRIES:
        raise ActionError("Pick a country from the list.")
    if language and language not in LANGUAGES:
        raise ActionError("Pick a language from the list.")
    youtube = _youtube(conn, channel_id, services)
    live = yt.channel_setup(youtube)
    yt.update_branding(youtube, live["id"], live["branding"], channel={
        "description": description, "keywords": keywords, "country": country, "defaultLanguage": language,
    })
    _quota(conn, 1 + yt.WRITE_COST)


def save_banner(conn, channel_id: int, data: bytes, services=None) -> None:
    mimetype = _check_image(data, BANNER_MAX_BYTES, BANNER_MIN, "banner", ("JPEG", "PNG"))
    from PIL import Image

    width, height = Image.open(io.BytesIO(data)).size
    if abs(width / height - 16 / 9) > 0.02:
        raise ActionError(f"The banner is {width}×{height}; it needs a 16:9 shape, ideally 2560×1440.")
    youtube = _youtube(conn, channel_id, services)
    with _temp_file(data) as path:
        url = yt.upload_banner(youtube, path, mimetype)
    live = yt.channel_setup(youtube)
    yt.update_branding(youtube, live["id"], live["branding"], image={"bannerExternalUrl": url})
    _quota(conn, 1 + 2 * yt.WRITE_COST)


def save_watermark(conn, channel_id: int, data: bytes, timing: str, services=None) -> None:
    mimetype = _check_image(data, WATERMARK_MAX_BYTES, WATERMARK_MIN, "watermark", ("JPEG", "PNG", "GIF"))
    timings = {"end": ("offsetFromEnd", 15000), "start": ("offsetFromStart", 0)}
    if timing not in timings:
        raise ActionError("Pick when the watermark shows.")
    youtube = _youtube(conn, channel_id, services)
    channel = _youtube_id(conn, channel_id)
    with _temp_file(data) as path:
        yt.set_watermark(youtube, channel, path, mimetype, *timings[timing])
    _quota(conn, yt.WRITE_COST)


def remove_watermark(conn, channel_id: int, services=None) -> None:
    yt.unset_watermark(_youtube(conn, channel_id, services), _youtube_id(conn, channel_id))
    _quota(conn, yt.WRITE_COST)


def save_trailer(conn, channel_id: int, video_id: str, services=None) -> None:
    video_id = video_id.strip()
    if video_id and not re.fullmatch(r"[\w-]{11}", video_id):
        raise ActionError("Pick a video from the list.")
    youtube = _youtube(conn, channel_id, services)
    live = yt.channel_setup(youtube)
    branding = json.loads(json.dumps(live["branding"]))
    if not video_id:
        branding.get("channel", {}).pop("unsubscribedTrailer", None)
    yt.update_branding(youtube, live["id"], branding, channel={"unsubscribedTrailer": video_id or None})
    _quota(conn, 1 + yt.WRITE_COST)


def create_playlist(conn, channel_id: int, title: str, description: str, privacy: str, use_for_uploads: bool, services=None) -> str:
    if privacy not in PRIVACY:
        raise ActionError("Pick who can see the playlist.")
    if not title.strip():
        raise ActionError("Give the playlist a title.")
    playlist_id = yt.create_playlist(_youtube(conn, channel_id, services), title.strip(), description.strip(), privacy)
    _quota(conn, yt.WRITE_COST)
    if use_for_uploads:
        set_upload_playlist(conn, channel_id, playlist_id)
    return playlist_id


# ---------- Gemini ----------

ABOUT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "description": {"type": "STRING", "description": "Channel description, 600-900 characters, 2-4 short paragraphs."},
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"}, "minItems": 8, "maxItems": 15, "description": "Search keywords, lowercase, 1-3 words each."},
    },
    "required": ["description", "keywords"],
}


def write_about(conn, channel_id: int, client=None) -> Dict[str, Any]:
    """A draft description and keywords for the channel's niche; nothing is saved."""
    from webapp import ai_drafts
    from providers.ai.gemini import Gemini, GeminiError

    row = conn.execute("SELECT name, niche FROM channels WHERE id = ?", (channel_id,)).fetchone()
    spec = NICHES.get(row["niche"])
    if not client:
        key, model = ai_drafts.api_key(), db.get_setting(conn, "gemini_model")
        if not key or not model:
            raise ActionError("Add your Gemini API key in Settings first.")
        client = Gemini(key, model)
    titles = [r[0] for r in conn.execute("SELECT title FROM videos WHERE channel_id = ? ORDER BY id DESC LIMIT 12", (channel_id,))]
    prompt = "\n".join(filter(None, [
        f"Write the YouTube channel 'About' description and search keywords for the channel \"{row['name']}\".",
        f"Niche: {spec.name}. Audience and tone: {spec.audience_and_tone}" if spec else "",
        f"On-screen language: {spec.language}. Write the description in that language (Hindi channels: Hindi, may mix in English keywords)." if spec else "",
        "Recent video titles: " + "; ".join(titles) if titles else "",
        "Say what viewers get and how often, invite them to subscribe. No made-up facts, numbers or links, no < or > characters, no hashtags.",
    ]))
    try:
        answer = client.generate_json(prompt, ABOUT_SCHEMA, temperature=0.7)
    except GeminiError as e:
        raise ActionError(str(e))
    description = re.sub(r"[<>]", "", answer.get("description", "")).strip()[:yt.ABOUT_LIMIT]
    keywords = [k.strip() for k in answer.get("keywords", []) if k.strip()]
    while keywords and len(yt.format_keywords(keywords)) > yt.KEYWORDS_LIMIT:
        keywords.pop()
    return {"description": description, "keywords": keywords}


# ---------- helpers ----------

def _youtube(conn, channel_id: int, services):
    if services:
        return services[0]
    from webapp.youtube_sync import _services

    row = conn.execute("SELECT is_mock, connection FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not row or row["is_mock"]:
        raise ActionError("Only real channels can be set up.")
    try:
        return _services(conn, channel_id)[0]
    except yt.NotAuthorized as e:
        raise ActionError(str(e))


def _youtube_id(conn, channel_id: int) -> str:
    row = conn.execute("SELECT youtube_channel_id FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not row or not row["youtube_channel_id"]:
        raise ActionError("Connect this channel to YouTube first.")
    return row["youtube_channel_id"]


def _quota(conn, units: int) -> None:
    from webapp.youtube_sync import _add_quota

    _add_quota(conn, units)


def _check_image(data: bytes, max_bytes: int, min_size, what: str, formats) -> str:
    from PIL import Image, UnidentifiedImageError

    if not data:
        raise ActionError(f"Choose a {what} image.")
    if len(data) > max_bytes:
        raise ActionError(f"The {what} is {len(data) / 1024 / 1024:.1f} MB; YouTube allows {max_bytes // 1024 // 1024} MB.")
    try:
        image = Image.open(io.BytesIO(data))
    except UnidentifiedImageError:
        raise ActionError(f"That {what} file isn't an image.")
    if image.format not in formats:
        raise ActionError(f"The {what} must be {' or '.join(formats)}.")
    if image.size[0] < min_size[0] or image.size[1] < min_size[1]:
        raise ActionError(f"The {what} is {image.size[0]}×{image.size[1]}; it must be at least {min_size[0]}×{min_size[1]}.")
    return IMAGE_TYPES[image.format]


class _temp_file:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self) -> str:
        fd, self.path = tempfile.mkstemp(prefix="hub-image-")
        with os.fdopen(fd, "wb") as f:
            f.write(self.data)
        return self.path

    def __exit__(self, *exc):
        try:
            os.remove(self.path)
        except OSError:
            pass
