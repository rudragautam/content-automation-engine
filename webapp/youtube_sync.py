"""The hub's YouTube connection: OAuth per channel, uploads and stats sync.

Secrets live under <hub dir>/secrets (inside output/, which git ignores):
    client_secret.json       the OAuth client downloaded from Google Cloud
    tokens/<channel id>.json one refresh token per hub channel
"""

import datetime as dt
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from content_templates.specs import NICHES
from publishing import youtube as yt
from webapp import db, timeutil
from webapp.queue import ActionError, TIME_RE

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 15 * 60
STATS_DAYS = 90
CATEGORY = {  # YouTube category IDs: 27 Education, 28 Science & Technology, 24 Entertainment
    "focus_habits": "27", "geeta_gyaan": "27", "general_quiz": "27", "science_quiz": "28",
    "science_story": "28", "indian_traditional_story": "24", "indian_heritage_story": "27",
    "crime_files": "24", "ai_neural_intelligence": "28", "ai_digital_future": "28",
}

_pending: Dict[str, Dict[str, Any]] = {}  # OAuth state -> channel and PKCE verifier
_upload_lock = threading.Lock()


def secrets_dir() -> str:
    return os.path.join(db.HUB_DIR, "secrets")


def client_path() -> str:
    return os.path.join(secrets_dir(), "client_secret.json")


def token_path(channel_id: int) -> str:
    return os.path.join(secrets_dir(), "tokens", f"{int(channel_id)}.json")


def redirect_uri(base_url: str) -> str:
    return base_url.rstrip("/") + "/oauth/callback"


# ---------- client file ----------

def client_status(base_url: str) -> Dict[str, Any]:
    uri = redirect_uri(base_url)
    if not os.path.exists(client_path()):
        return {"present": False, "redirect_uri": uri}
    try:
        cfg = yt.read_client_config(client_path())
    except yt.YouTubeError as e:
        return {"present": False, "redirect_uri": uri, "error": str(e)}
    cid = cfg["client_id"]
    registered = cfg["kind"] == "installed" or uri in cfg["redirect_uris"]
    # Opened at another address than the registered one (localhost vs 127.0.0.1): say where sign-in works.
    others = [u[: -len("/oauth/callback")] for u in cfg["redirect_uris"] if u.endswith("/oauth/callback") and u != uri]
    return {"present": True, "kind": cfg["kind"], "client_id": cid[:12] + "…" + cid[-28:], "redirect_uri": uri, "redirect_ok": registered,
            "use_instead": "" if registered or not others else others[0]}


def save_client_file(data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ActionError("That file isn't text. Download the OAuth client JSON from Google Cloud → Credentials.")
    try:
        yt.parse_client_config(text)
    except yt.YouTubeError as e:
        raise ActionError(str(e))
    os.makedirs(secrets_dir(), exist_ok=True)
    with open(client_path(), "w", encoding="utf-8") as f:
        f.write(text)


def save_client_keys(client_id: str, client_secret: str, base_url: str) -> None:
    """Build the client file from a pasted Client ID and secret (Google Cloud no longer offers the
    JSON download after the client is created)."""
    client_id, client_secret = client_id.strip(), client_secret.strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise ActionError("That isn't a Client ID; it ends in .apps.googleusercontent.com. Copy it from Google Cloud → Credentials → your OAuth client.")
    if not client_secret or " " in client_secret:
        raise ActionError("Paste the Client secret from the same OAuth client.")
    config = {"web": {
        "client_id": client_id, "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [redirect_uri(base_url)],
    }}
    save_client_file(json.dumps(config, indent=2).encode("utf-8"))


# ---------- channels ----------

def add_channel(conn, name: str, niche: str, slots: str, handle: str = "", angle: str = "") -> int:
    from webapp.channel_names import ANGLE_LIMIT, handle as clean_handle

    name = name.strip()
    if not name:
        raise ActionError("Give the channel a name.")
    if niche not in NICHES:
        raise ActionError("Pick a niche.")
    channel_id = _insert_channel(conn, name, niche, _publish_times(slots), clean_handle(handle) if handle.strip() else "")
    if angle.strip():
        conn.execute("UPDATE channels SET angle = ? WHERE id = ?", (angle.strip()[:ANGLE_LIMIT], channel_id))
    return channel_id


def _publish_times(slots: str) -> List[str]:
    times = sorted({t.strip() for t in slots.split(",") if t.strip()}) or ["19:00"]
    bad = [t for t in times if not TIME_RE.match(t)]
    if bad:
        raise ActionError(f"Not a time (HH:MM, 24-hour): {', '.join(bad)}")
    return times


def _insert_channel(conn, name: str, niche: str, times: List[str], handle: str = "") -> int:
    channel_id = conn.execute(
        "INSERT INTO channels (name, handle, niche, connection, created_at, is_mock) VALUES (?, ?, ?, 'not_connected', ?, 0)",
        (name[:100], handle, niche, timeutil.now_local().date().isoformat())).lastrowid
    conn.executemany("INSERT INTO channel_slots (channel_id, time) VALUES (?, ?)", [(channel_id, t) for t in times])
    return channel_id


def remove_mock_data(conn) -> int:
    ids = [r[0] for r in conn.execute("SELECT id FROM channels WHERE is_mock = 1")]
    marks = ",".join("?" * len(ids))
    if ids:
        conn.execute(f"DELETE FROM uploads WHERE channel_id IN ({marks})", ids)
        conn.execute(f"DELETE FROM channels WHERE id IN ({marks})", ids)  # cascades to videos, stats, slots
    conn.execute("DELETE FROM videos WHERE is_mock = 1")
    conn.execute("DELETE FROM quota_usage")
    db.set_setting(conn, "mock_removed", timeutil.fmt(timeutil.now_local()))
    return len(ids)


# ---------- connect ----------

def start_connect(conn, channel_id: int, base_url: str) -> str:
    channel = conn.execute("SELECT is_mock FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not channel:
        raise ActionError("Channel not found.")
    if channel["is_mock"]:
        raise ActionError("This is a mock channel. Connect your real channel from Settings instead.")
    return _sign_in_url({"channel_id": channel_id}, base_url)


def start_new_connect(niche: str, slots: str, base_url: str) -> str:
    """Sign in first; the hub channel is created from whichever YouTube channel the user picks."""
    if niche not in NICHES:
        raise ActionError("Pick a niche.")
    return _sign_in_url({"channel_id": None, "niche": niche, "slots": _publish_times(slots)}, base_url)


def _sign_in_url(target: Dict[str, Any], base_url: str) -> str:
    if not os.path.exists(client_path()):
        raise ActionError("Upload your Google OAuth client file in Settings first.")
    now = time.time()
    for key in [k for k, v in _pending.items() if now - v["at"] > STATE_TTL_SECONDS]:
        _pending.pop(key, None)
    state = secrets.token_urlsafe(24)
    url, verifier = yt.authorization_url(client_path(), redirect_uri(base_url), state)
    _pending[state] = {**target, "verifier": verifier, "at": now}
    return url


def finish_connect(conn, state: str, code: str, base_url: str) -> int:
    pending = _pending.pop(state, None)
    if not pending or time.time() - pending["at"] > STATE_TTL_SECONDS:
        raise ActionError("This sign-in link expired or was already used. Start again from Settings or the channel page.")
    creds = yt.exchange_code(client_path(), redirect_uri(base_url), state, code, pending["verifier"])
    youtube, _ = yt.build_services(creds)
    found = yt.my_channel(youtube)
    channel_id = pending["channel_id"]
    if channel_id is None:
        # The same YouTube channel connected again just gets a fresh sign-in; its niche and times stay.
        existing = conn.execute("SELECT id FROM channels WHERE youtube_channel_id = ? AND is_mock = 0", (found["id"],)).fetchone()
        # A channel added by name for this niche and still waiting for its YouTube channel takes this sign-in.
        waiting = conn.execute("SELECT id FROM channels WHERE is_mock = 0 AND niche = ? AND COALESCE(youtube_channel_id, '') = ''", (pending["niche"],)).fetchall()
        if existing:
            channel_id = existing["id"]
        elif len(waiting) == 1:
            channel_id = waiting[0]["id"]
        else:
            channel_id = _insert_channel(conn, found["title"], pending["niche"], pending["slots"], found["handle"])
    bind_channel(conn, channel_id, found)
    account = yt.account_email(creds)
    if account:
        conn.execute("UPDATE channels SET google_account = ? WHERE id = ?", (account, channel_id))
    yt.save_credentials(creds, token_path(channel_id))
    return channel_id


def set_niche(conn, channel_id: int, niche: str) -> None:
    """Move a channel to another niche. Not while it has content waiting to render: that was written for the old niche."""
    if niche not in NICHES:
        raise ActionError("Pick a niche.")
    waiting = conn.execute(
        "SELECT COUNT(*) FROM videos WHERE channel_id = ? AND content_json IS NOT NULL "
        "AND status NOT IN ('rendered', 'uploading', 'scheduled', 'published')", (channel_id,)).fetchone()[0]
    if waiting:
        raise ActionError(f"This channel has {waiting} video{'s' if waiting != 1 else ''} waiting to render, written for its current niche. "
                          "Render or delete them first, then change the niche.")
    conn.execute("UPDATE channels SET niche = ? WHERE id = ? AND is_mock = 0", (niche, channel_id))


def bind_channel(conn, channel_id: int, found: Dict[str, Any]) -> None:
    """Link a hub channel to the YouTube channel the user signed in as, refusing mix-ups."""
    row = conn.execute("SELECT youtube_channel_id, name FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if row["youtube_channel_id"] and row["youtube_channel_id"] != found["id"]:
        raise ActionError(f"You signed in as “{found['title']}”, but {row['name']} is linked to a different YouTube channel. "
                          "Connect again and pick the right channel on Google's screen.")
    other = conn.execute("SELECT name FROM channels WHERE youtube_channel_id = ? AND id != ?", (found["id"], channel_id)).fetchone()
    if other:
        raise ActionError(f"“{found['title']}” is already connected as {other['name']} in the hub.")
    conn.execute(
        "UPDATE channels SET youtube_channel_id = ?, connection = 'connected', subscribers = ?, "
        "handle = CASE WHEN handle = '' THEN ? ELSE handle END WHERE id = ?",
        (found["id"], found["subscribers"], found["handle"], channel_id))


def disconnect(conn, channel_id: int) -> None:
    path = token_path(channel_id)
    if os.path.exists(path):
        os.remove(path)
    conn.execute("UPDATE channels SET connection = 'not_connected' WHERE id = ? AND is_mock = 0", (channel_id,))


def _services(conn, channel_id: int):
    try:
        creds = yt.load_credentials(token_path(channel_id))
    except yt.NotAuthorized:
        conn.execute("UPDATE channels SET connection = 'expired' WHERE id = ? AND is_mock = 0", (channel_id,))
        conn.commit()
        raise
    return yt.build_services(creds)


# ---------- upload ----------

def start_upload(conn, video_id: int) -> None:
    row = conn.execute("SELECT v.status, v.video_path, v.publish_at, c.connection, c.is_mock FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (video_id,)).fetchone()
    if not row:
        raise ActionError("Video not found.")
    if row["status"] != "rendered" or not row["video_path"] or not os.path.exists(row["video_path"]):
        raise ActionError("Render the video first.")
    if row["connection"] != "connected":
        raise ActionError("This channel isn't connected to YouTube.")
    if row["is_mock"]:  # mock channels only mark the video, nothing leaves the PC
        conn.execute("UPDATE videos SET status = 'scheduled' WHERE id = ?", (video_id,))
        return
    if row["publish_at"] and timeutil.parse(row["publish_at"]) <= timeutil.now_local() + dt.timedelta(minutes=15):
        raise ActionError("The publish time is less than 15 minutes away; move it later first.")
    conn.execute("UPDATE videos SET status = 'uploading', upload_progress = 0, error = NULL WHERE id = ?", (video_id,))
    conn.commit()
    threading.Thread(target=upload_now, args=(video_id,), daemon=True).start()


def upload_now(video_id: int, services=None) -> None:
    with _upload_lock:
        conn = db.connect()
        try:
            v = conn.execute("SELECT v.*, c.niche, c.timezone FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (video_id,)).fetchone()
            youtube, _ = services or _services(conn, v["channel_id"])
            from webapp import channel_setup

            prefs = channel_setup.defaults(conn, v["channel_id"])
            footer = prefs["description_footer"]
            description = "\n\n".join(part for part in (v["description"], footer) if part)
            own_tags = [t.strip() for t in v["tags"].split(",") if t.strip()]
            tags = own_tags + [t for t in prefs["default_tags"] if t.lower() not in {o.lower() for o in own_tags}]
            body = yt.upload_body(
                v["title"], description, tags,
                yt.to_utc_rfc3339(v["publish_at"], v["timezone"]) if v["publish_at"] else None,
                category_id=prefs["category_id"], language=prefs["language"],
                made_for_kids=prefs["made_for_kids"], synthetic_media=prefs["synthetic_media"],
            )

            def progress(p):
                conn.execute("UPDATE videos SET upload_progress = ? WHERE id = ?", (round(p * 100, 1), video_id))
                conn.commit()

            yt_id = yt.upload_video(youtube, v["video_path"], body, progress)
            _add_quota(conn, yt.UPLOAD_COST)
            conn.execute("UPDATE videos SET status = 'scheduled', youtube_video_id = ?, upload_progress = 100 WHERE id = ?", (yt_id, video_id))
            conn.commit()
            if prefs["playlist_id"]:
                try:  # the video is on YouTube either way; a playlist hiccup shouldn't mark it failed
                    yt.add_to_playlist(youtube, prefs["playlist_id"], yt_id)
                    _add_quota(conn, yt.WRITE_COST)
                except yt.YouTubeError as e:
                    conn.execute("UPDATE videos SET error = ? WHERE id = ?", (f"Uploaded, but not added to the playlist: {e}"[:500], video_id))
        except yt.YouTubeError as e:
            conn.execute("UPDATE videos SET status = 'rendered', error = ? WHERE id = ?", (f"Upload failed: {e}"[:500], video_id))
        except Exception as e:
            logger.exception("Upload of video %s failed", video_id)
            conn.execute("UPDATE videos SET status = 'rendered', error = ? WHERE id = ?", (f"Upload failed: {e}"[:500], video_id))
        finally:
            conn.commit()
            conn.close()


def _add_quota(conn, units: int) -> None:
    today = timeutil.now_local().date().isoformat()
    conn.execute("INSERT INTO quota_usage (date, units) VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET units = units + excluded.units", (today, units))


def reschedule(conn, video_id: int, publish_at: str, services=None) -> str:
    """Change a video's publish time, on YouTube too when it is already uploaded there."""
    from webapp import queue

    value = queue.reschedule(conn, video_id, publish_at)
    v = conn.execute("SELECT v.youtube_video_id, v.channel_id, c.timezone, c.is_mock FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (video_id,)).fetchone()
    if v["youtube_video_id"] and not v["is_mock"]:
        if timeutil.parse(value) <= timeutil.now_local() + dt.timedelta(minutes=15):
            raise ActionError("Pick a time at least 15 minutes from now for a video already on YouTube.")
        try:
            youtube, _ = services or _services(conn, v["channel_id"])
            yt.set_publish_time(youtube, v["youtube_video_id"], yt.to_utc_rfc3339(value, v["timezone"]))
        except yt.YouTubeError as e:
            raise ActionError(f"YouTube didn't accept the new time: {e}")
        _add_quota(conn, 51)
    return value


# ---------- stats ----------

def sync_channel(conn, channel_id: int, services=None) -> Dict[str, int]:
    """Pull subscribers, daily stats and recent videos from YouTube into the hub."""
    row = conn.execute("SELECT is_mock, connection, timezone FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not row or row["is_mock"]:
        raise ActionError("Only real, connected channels can sync from YouTube.")
    try:
        youtube, analytics = services or _services(conn, channel_id)
        info = yt.my_channel(youtube)
        today = timeutil.now_local().date()
        days = yt.daily_stats(analytics, today - dt.timedelta(days=STATS_DAYS), today - dt.timedelta(days=1))
        videos = yt.recent_videos(youtube, info["uploads_playlist"]) if info["uploads_playlist"] else []
    except yt.NotAuthorized as e:
        raise ActionError(str(e))
    except yt.YouTubeError as e:
        raise ActionError(f"Sync failed: {e}")

    conn.execute("UPDATE channels SET subscribers = ?, last_synced_at = ? WHERE id = ?", (info["subscribers"], timeutil.fmt(timeutil.now_local()), channel_id))
    conn.executemany(
        "INSERT OR REPLACE INTO daily_stats (channel_id, date, views, watch_minutes, subs_gained, subs_lost) VALUES (?,?,?,?,?,?)",
        [(channel_id, d["date"], d["views"], d["watch_minutes"], d["subs_gained"], d["subs_lost"]) for d in days])
    for v in videos:
        local = _to_local(v["publish_at"] or v["published_at"], row["timezone"])
        status = "published" if v["privacy"] == "public" else "scheduled" if v["publish_at"] else None
        existing = conn.execute("SELECT id FROM videos WHERE youtube_video_id = ?", (v["id"],)).fetchone()
        if existing:
            conn.execute("UPDATE videos SET views = ?, likes = ?, comments = ?, status = COALESCE(?, status), title = ? WHERE id = ?",
                         (v["views"], v["likes"], v["comments"], status, v["title"], existing["id"]))
        elif status:
            conn.execute(
                "INSERT INTO videos (channel_id, video_ref, title, status, publish_at, duration_s, views, likes, comments, youtube_video_id, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (channel_id, v["id"], v["title"], status, local, v["duration_s"], v["views"], v["likes"], v["comments"], v["id"], timeutil.fmt(timeutil.now_local())))
    _add_quota(conn, 5)
    return {"days": len(days), "videos": len(videos)}


def _to_local(utc_iso: Optional[str], timezone: str) -> Optional[str]:
    if not utc_iso:
        return None
    from zoneinfo import ZoneInfo

    when = dt.datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    return timeutil.fmt(when.astimezone(ZoneInfo(timezone)).replace(tzinfo=None))
