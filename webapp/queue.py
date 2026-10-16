"""Write-side actions: scheduling, content import, audio library and rendering."""

import datetime as dt
import json
import logging
import os
import re
import shutil
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from content_templates import get_spec, read_workbook
from content_templates.excel import ImportResult
from webapp import db, timeutil

logger = logging.getLogger(__name__)

EDITABLE = ("ready", "rendered", "scheduled", "failed")  # scheduled ones on real YouTube need re-uploading for now
QUEUED = ("ready", "rendering", "rendered", "uploading", "scheduled")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ActionError(ValueError):
    """A user-facing reason an action was refused."""


def can_render(niche: str) -> bool:
    """True when the niche's template has a video workflow."""
    from workflows.registry import has_workflow

    return has_workflow(get_spec(niche).template_id)


# ---------- scheduling ----------

def slots(conn, channel_id: int) -> List[str]:
    return [r[0] for r in conn.execute("SELECT time FROM channel_slots WHERE channel_id = ? ORDER BY time", (channel_id,))]


def set_slots(conn, channel_id: int, times: List[str]) -> List[str]:
    cleaned = sorted({t.strip() for t in times if t.strip()})
    bad = [t for t in cleaned if not TIME_RE.match(t)]
    if bad:
        raise ActionError(f"Not a time (HH:MM, 24-hour): {', '.join(bad)}")
    if not cleaned:
        raise ActionError("Keep at least one publish slot.")
    conn.execute("DELETE FROM channel_slots WHERE channel_id = ?", (channel_id,))
    conn.executemany("INSERT INTO channel_slots (channel_id, time) VALUES (?, ?)", [(channel_id, t) for t in cleaned])
    return cleaned


def next_free_slots(conn, channel_id: int, count: int, after: dt.datetime = None) -> List[str]:
    """The next `count` slot times that no queued video already uses."""
    times = slots(conn, channel_id)
    if not times:
        raise ActionError("This channel has no publish slots; add one in its settings.")
    after = after or timeutil.now_local()
    taken = {r[0] for r in conn.execute(
        f"SELECT publish_at FROM videos WHERE channel_id = ? AND status IN ({','.join('?' * len(QUEUED))}) AND publish_at > ?",
        (channel_id, *QUEUED, timeutil.fmt(after)))}
    found, day = [], after.date()
    while len(found) < count:
        for t in times:
            candidate = f"{day.isoformat()}T{t}"
            if timeutil.parse(candidate) > after and candidate not in taken:
                found.append(candidate)
                taken.add(candidate)
                if len(found) == count:
                    break
        day += dt.timedelta(days=1)
    return found


def reschedule(conn, video_id: int, publish_at: str) -> str:
    video = conn.execute("SELECT status FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not video:
        raise ActionError("Video not found.")
    if video["status"] not in EDITABLE:
        raise ActionError(f"A {video['status']} video can't be rescheduled.")
    try:
        when = dt.datetime.fromisoformat(publish_at)
    except ValueError:
        raise ActionError("Pick a valid date and time.")
    if when <= timeutil.now_local():
        raise ActionError("The publish time must be in the future.")
    value = timeutil.fmt(when)
    status = "scheduled" if video["status"] == "failed" else video["status"]
    conn.execute("UPDATE videos SET publish_at = ?, status = ?, error = NULL WHERE id = ?", (value, status, video_id))
    return value


# ---------- content import ----------

def import_content(conn, niche: str, channel_id: int, filename: str, data: bytes) -> Tuple[ImportResult, Optional[int]]:
    """Validate an uploaded sheet; if it is clean, queue every row as a ready video."""
    channel = conn.execute("SELECT niche FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not channel or channel["niche"] != niche:
        raise ActionError("Pick a channel from this niche.")
    result = read_workbook(data, get_spec(niche))
    if not result.ok:
        return result, None

    existing = {r[0] for r in conn.execute("SELECT video_ref FROM videos WHERE channel_id = ?", (channel_id,))}
    clashes = [v["video_id"] for v in result.videos if v["video_id"] in existing]
    if clashes:
        result.errors.extend({"row": v["row"], "column": "video_id", "message": f"'{v['video_id']}' is already in this channel's queue"}
                             for v in result.videos if v["video_id"] in clashes)
        return result, None

    now = timeutil.now_local()
    for v in result.videos:
        if v["publish_at"] and timeutil.parse(v["publish_at"]) <= now:
            result.errors.append({"row": v["row"], "column": "publish_at", "message": f"{v['publish_at'].replace('T', ' ')} is in the past"})
    if result.errors:
        return result, None

    auto = iter(next_free_slots(conn, channel_id, sum(1 for v in result.videos if not v["publish_at"])))
    created = timeutil.fmt(now)
    upload_id = conn.execute(
        "INSERT INTO uploads (niche, channel_id, filename, uploaded_at, videos_added) VALUES (?,?,?,?,?)",
        (niche, channel_id, filename, created, len(result.videos))).lastrowid
    for v in result.videos:
        conn.execute(
            "INSERT INTO videos (channel_id, video_ref, title, description, tags, status, publish_at, content_json, upload_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (channel_id, v["video_id"], v["youtube"]["title"], v["youtube"]["description"], ", ".join(v["youtube"]["tags"]),
             "ready", v["publish_at"] or next(auto), json.dumps(v["content"], ensure_ascii=False), upload_id, created))
    return result, upload_id


# ---------- audio library ----------

def audio_dir(niche: str) -> str:
    path = os.path.join(db.HUB_DIR, "audio", niche)
    os.makedirs(path, exist_ok=True)
    return path


def add_audio(conn, niche: str, original_name: str, data: bytes, licence: str) -> int:
    from rendering.audio import AUDIO_EXTENSIONS, media_duration

    ext = os.path.splitext(original_name)[1].lower()
    if ext not in AUDIO_EXTENSIONS:
        raise ActionError(f"{original_name}: use one of {', '.join(AUDIO_EXTENSIONS)}")
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(audio_dir(niche), stored)
    with open(path, "wb") as f:
        f.write(data)
    duration = media_duration(path)
    if not duration:
        os.remove(path)
        raise ActionError(f"{original_name}: not a playable audio file")
    title = os.path.splitext(os.path.basename(original_name))[0][:120]
    return conn.execute(
        "INSERT INTO audio (niche, title, filename, licence, duration_s, uploaded_at) VALUES (?,?,?,?,?,?)",
        (niche, title, stored, licence.strip()[:200], round(duration, 1), timeutil.fmt(timeutil.now_local()))).lastrowid


def audio_path(row) -> str:
    return os.path.join(audio_dir(row["niche"]), row["filename"])


def delete_audio(conn, audio_id: int) -> None:
    row = conn.execute("SELECT * FROM audio WHERE id = ?", (audio_id,)).fetchone()
    if not row:
        raise ActionError("Track not found.")
    conn.execute("DELETE FROM audio WHERE id = ?", (audio_id,))
    if os.path.exists(audio_path(row)):
        os.remove(audio_path(row))


def choose_audio(conn, niche: str):
    """Random track for the niche, avoiding the one used most recently."""
    from rendering.audio import pick_track

    rows = conn.execute("SELECT * FROM audio WHERE niche = ?", (niche,)).fetchall()
    if not rows:
        return None
    last = conn.execute("SELECT id FROM audio WHERE niche = ? AND last_used_at IS NOT NULL ORDER BY last_used_at DESC LIMIT 1", (niche,)).fetchone()
    chosen_id = pick_track([r["id"] for r in rows], avoid=last[0] if last else None)
    return next(r for r in rows if r["id"] == chosen_id)


# ---------- rendering ----------

_render_lock = threading.Lock()


def start_render(conn, video_id: int) -> None:
    row = conn.execute("SELECT v.status, v.content_json, c.niche FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (video_id,)).fetchone()
    if not row:
        raise ActionError("Video not found.")
    if not row["content_json"]:
        raise ActionError("This video has no slide content to render; upload it through a content sheet.")
    if not can_render(row["niche"]):
        raise ActionError("Rendering for this template isn't built yet. Only Focus & Habits renders today.")
    if row["status"] not in ("ready", "failed", "rendered"):
        raise ActionError(f"A {row['status']} video can't be rendered.")
    conn.execute("UPDATE videos SET status = 'rendering', error = NULL WHERE id = ?", (video_id,))
    conn.commit()
    threading.Thread(target=_render, args=(video_id,), daemon=True).start()


def _render(video_id: int) -> None:
    from rendering.audio import add_background_audio
    from workflows.registry import get_workflow

    with _render_lock:  # one render at a time keeps the PC responsive
        conn = db.connect()
        try:
            video = conn.execute("SELECT v.*, c.niche FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (video_id,)).fetchone()
            workflow = get_workflow(get_spec(video["niche"]).template_id)
            result = workflow.run(json.loads(video["content_json"]), output_dir=os.path.join(db.HUB_DIR, "renders"), render=True)
            if not result.get("success"):
                raise RuntimeError(result.get("error") or result.get("video", {}).get("error") or "render failed")
            silent = result["video"]["video_path"]
            final, audio_id = silent, None
            track = choose_audio(conn, video["niche"])
            if track:
                final = os.path.join(os.path.dirname(silent), "final_with_audio.mp4")
                add_background_audio(silent, audio_path(track), final)
                audio_id = track["id"]
                conn.execute("UPDATE audio SET last_used_at = ?, times_used = times_used + 1 WHERE id = ?", (timeutil.fmt(timeutil.now_local()), audio_id))
            conn.execute("UPDATE videos SET status = 'rendered', video_path = ?, audio_id = ?, duration_s = ? WHERE id = ?",
                         (final, audio_id, result["total_seconds"], video_id))
        except Exception as e:
            logger.exception("Render of video %s failed", video_id)
            conn.execute("UPDATE videos SET status = 'failed', error = ? WHERE id = ?", (f"Render failed: {e}"[:500], video_id))
        finally:
            conn.commit()
            conn.close()


def delete_video(conn, video_id: int) -> None:
    row = conn.execute("SELECT v.status, v.video_path, v.youtube_video_id, c.is_mock FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?", (video_id,)).fetchone()
    if not row:
        raise ActionError("Video not found.")
    if row["youtube_video_id"] and not row["is_mock"]:
        raise ActionError("This video is already on YouTube. Delete it in YouTube Studio; the next sync updates the hub.")
    if row["status"] in ("published", "rendering", "uploading"):
        raise ActionError(f"A {row['status']} video can't be removed here.")
    conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    if row["video_path"]:
        run_dir = os.path.abspath(os.path.dirname(os.path.dirname(row["video_path"])))
        renders = os.path.abspath(os.path.join(db.HUB_DIR, "renders"))
        if os.path.dirname(run_dir) == renders:  # only ever delete our own render folders
            shutil.rmtree(run_dir, ignore_errors=True)
