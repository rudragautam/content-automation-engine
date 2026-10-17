"""Gemini in the hub: API key and model settings, and generated drafts awaiting review.

A draft holds what the model wrote for one request. Nothing reaches a
channel's queue until the user reviews the draft and adds it.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from content_templates import NICHES, get_spec
from content_templates.ai import MAX_VIDEOS, generate
from content_templates.excel import ImportResult, read_rows, workbook_with_rows
from providers.ai.gemini import Gemini, GeminiError, pick_default_model
from webapp import db, timeutil
from webapp.queue import ActionError, queue_videos

logger = logging.getLogger(__name__)

AVOID_TITLES = 60


# ---------- key and model ----------

def key_path() -> str:
    return os.path.join(db.HUB_DIR, "secrets", "gemini.json")


def api_key() -> Optional[str]:
    if os.path.exists(key_path()):
        with open(key_path(), encoding="utf-8") as f:
            return json.load(f).get("api_key")
    return os.environ.get("GEMINI_API_KEY")


def save_key(conn, key: str) -> List[Dict[str, str]]:
    """Check the key by listing its models, then store it and pick a default model."""
    key = key.strip()
    if not key:
        raise ActionError("Paste a Gemini API key.")
    try:
        client = Gemini(key)
        models = client.list_models()
        client.close()
    except GeminiError as e:
        raise ActionError(str(e))
    if not models:
        raise ActionError("This key works but can't use any text models.")
    os.makedirs(os.path.dirname(key_path()), exist_ok=True)
    with open(key_path(), "w", encoding="utf-8") as f:
        json.dump({"api_key": key}, f)
    db.set_setting(conn, "gemini_models", json.dumps(models))
    if db.get_setting(conn, "gemini_model") not in {m["id"] for m in models}:
        db.set_setting(conn, "gemini_model", pick_default_model(models))
    return models


def remove_key(conn) -> None:
    if os.path.exists(key_path()):
        os.remove(key_path())
    conn.execute("DELETE FROM settings WHERE key IN ('gemini_models', 'gemini_model')")


def set_model(conn, model: str) -> None:
    if model not in {m["id"] for m in models(conn)}:
        raise ActionError("Pick a model from the list.")
    db.set_setting(conn, "gemini_model", model)


def models(conn) -> List[Dict[str, str]]:
    return json.loads(db.get_setting(conn, "gemini_models", "[]"))


def status(conn) -> Dict[str, Any]:
    key = api_key()
    return {
        "configured": bool(key),
        "from_env": bool(key) and not os.path.exists(key_path()),
        "masked": (key[:4] + "…" + key[-4:]) if key and len(key) > 10 else "",
        "model": db.get_setting(conn, "gemini_model"),
        "models": models(conn),
    }


# ---------- drafts ----------

def start_draft(conn, niche: str, channel_id: int, topic: str, count: int, instructions: str) -> int:
    if niche not in NICHES:
        raise ActionError("Unknown niche.")
    channel = conn.execute("SELECT name, niche FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not channel or channel["niche"] != niche:
        raise ActionError("Pick a channel from this niche.")
    if not topic.strip():
        raise ActionError("Give a topic or theme.")
    if not api_key():
        raise ActionError("Add your Gemini API key in Settings first.")
    model = db.get_setting(conn, "gemini_model")
    if not model:
        raise ActionError("Pick a Gemini model in Settings first.")
    count = max(1, min(int(count or 1), MAX_VIDEOS))
    draft_id = conn.execute(
        "INSERT INTO drafts (niche, channel_id, topic, count, instructions, model, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (niche, channel_id, topic.strip()[:300], count, instructions.strip()[:1000], model, "generating", timeutil.fmt(timeutil.now_local()))).lastrowid
    conn.commit()
    threading.Thread(target=run_draft, args=(draft_id,), daemon=True).start()
    return draft_id


def run_draft(draft_id: int, client=None) -> None:
    conn = db.connect()
    try:
        d = conn.execute("SELECT d.*, c.name channel_name, c.angle FROM drafts d JOIN channels c ON c.id = d.channel_id WHERE d.id = ?", (draft_id,)).fetchone()
        # Channels sharing a niche differ by their angle, so it steers every draft.
        instructions = "\n".join(filter(None, [f"This channel's angle: {d['angle']}" if d["angle"] else "", d["instructions"]]))
        avoid = [r[0] for r in conn.execute(
            "SELECT v.title FROM videos v JOIN channels c ON c.id = v.channel_id WHERE c.niche = ? ORDER BY v.id DESC LIMIT ?", (d["niche"], AVOID_TITLES))]
        own = client or Gemini(api_key(), d["model"])
        try:
            result = generate(own, get_spec(d["niche"]), d["topic"], d["count"], d["channel_name"], instructions, avoid)
        finally:
            if client is None:
                own.close()
        conn.execute("UPDATE drafts SET status = 'ready', rows_json = ?, rejected_json = ? WHERE id = ?",
                     (json.dumps(result.rows, ensure_ascii=False), json.dumps(result.rejected, ensure_ascii=False), draft_id))
    except (GeminiError, ValueError) as e:
        conn.execute("UPDATE drafts SET status = 'failed', error = ? WHERE id = ?", (str(e)[:500], draft_id))
    except Exception as e:
        logger.exception("Draft %s failed", draft_id)
        conn.execute("UPDATE drafts SET status = 'failed', error = ? WHERE id = ?", (f"Generation failed: {e}"[:500], draft_id))
    finally:
        conn.commit()
        conn.close()


def load(conn, draft_id: int) -> Dict[str, Any]:
    d = conn.execute("SELECT d.*, c.name channel_name FROM drafts d JOIN channels c ON c.id = d.channel_id WHERE d.id = ?", (draft_id,)).fetchone()
    if not d:
        raise ActionError("Draft not found.")
    draft = dict(d)
    spec = get_spec(d["niche"])
    draft["items"] = []
    for i, row in enumerate(json.loads(d["rows_json"] or "[]"), start=1):
        checked = read_rows([row], spec, first_row=i)  # one row at a time, so results can't shift between rows
        draft["items"].append({
            "ok": checked.ok and bool(checked.videos), "row": row,
            "video": checked.videos[0] if checked.ok and checked.videos else None,
            "errors": [f"{e['column'] or ''}: {e['message']}".lstrip(": ") for e in checked.errors] or ([] if checked.videos else ["empty video"]),
        })
    draft["valid_count"] = sum(1 for item in draft["items"] if item["ok"])
    return draft


def add_to_queue(conn, draft_id: int) -> int:
    draft = load(conn, draft_id)
    if draft["status"] != "ready":
        raise ActionError("This draft isn't ready to queue.")
    videos = [item["video"] for item in draft["items"] if item["ok"]]
    if not videos:
        raise ActionError("No valid videos in this draft; download it as Excel, fix it and upload it.")
    result = ImportResult(videos=videos)
    upload_id = queue_videos(conn, draft["niche"], draft["channel_id"], f"Gemini: {draft['topic'][:80]}", result)
    if upload_id is None:
        raise ActionError("; ".join(e["message"] for e in result.errors))
    conn.execute("UPDATE drafts SET status = 'queued' WHERE id = ?", (draft_id,))
    return len(videos)


def excel(conn, draft_id: int) -> bytes:
    draft = load(conn, draft_id)
    return workbook_with_rows(get_spec(draft["niche"]), [item["row"] for item in draft["items"]])


def discard(conn, draft_id: int) -> None:
    conn.execute("UPDATE drafts SET status = 'discarded' WHERE id = ? AND status != 'queued'", (draft_id,))


def recent(conn, niche: str, limit: int = 8) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT d.id, d.topic, d.count, d.status, d.created_at, c.name channel_name FROM drafts d JOIN channels c ON c.id = d.channel_id "
        "WHERE d.niche = ? AND d.status != 'discarded' ORDER BY d.id DESC LIMIT ?", (niche, limit))]
