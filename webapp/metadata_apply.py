"""Changing a video's title, description and tags: limit checks, a before/after preview, backup and Undo.

A change targets either one row of a Gemini draft or a hub video that isn't on YouTube
yet; both change in the hub only and go out with the upload. Nothing here edits YouTube.
Every check counts what the upload will really send: the channel's description footer
and default tags are added then (webapp.youtube_sync.upload_now).
"""

import json
from typing import Any, Dict, List, Optional

from content_templates import get_spec
from content_templates.excel import read_rows
from publishing import youtube as yt
from webapp import channel_setup, timeutil
from webapp.queue import ActionError

LOCAL_STATUSES = ("ready", "rendered", "failed")  # hub videos whose metadata can still change before upload


# ---------- what the upload sends ----------

def parse_tags(text: str) -> List[str]:
    seen, out = set(), []
    for tag in (t.strip() for t in (text or "").replace("\n", ",").split(",")):
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def upload_metadata(prefs: Dict[str, Any], title: str, description: str, tags: List[str]) -> Dict[str, Any]:
    """Title, description and tags as the upload assembles them, before YouTube's limits are applied."""
    full = "\n\n".join(part for part in (description, prefs.get("description_footer", "")) if part)
    own = {t.lower() for t in tags}
    return {
        "title": yt.clean_text(title),
        "description": yt.clean_text(full),
        "tags": list(tags) + [t for t in prefs.get("default_tags", []) if t.lower() not in own],
    }


def limit_problems(meta: Dict[str, Any]) -> List[str]:
    problems = []
    if not meta["title"]:
        problems.append("The title is empty.")
    elif len(meta["title"]) > yt.TITLE_LIMIT:
        problems.append(f"The title is {len(meta['title'])} characters; YouTube allows {yt.TITLE_LIMIT}.")
    size = yt.description_bytes(meta["description"])
    if size > yt.DESCRIPTION_LIMIT:
        problems.append(f"The description (with the channel's footer) is {size:,} bytes; YouTube allows {yt.DESCRIPTION_LIMIT:,}. "
                        "Hindi letters take 3 bytes each.")
    length = yt.tags_length(meta["tags"])
    if length > yt.TAGS_LIMIT:
        problems.append(f"The tags (with the channel's default tags) come to {length} characters; YouTube allows {yt.TAGS_LIMIT}.")
    return problems


def measure(meta: Dict[str, Any]) -> Dict[str, int]:
    return {"title": len(meta["title"]), "description_bytes": yt.description_bytes(meta["description"]), "tags": yt.tags_length(meta["tags"])}


# ---------- targets ----------

def current(conn, s) -> Dict[str, Any]:
    """The target's title, description and tags as they are now in the hub."""
    if s["draft_id"]:
        row = _draft_row(conn, s)[1]
        return {"title": row.get("youtube_title", "") or "", "description": row.get("youtube_description", "") or "",
                "tags": parse_tags(row.get("youtube_tags", "") or "")}
    v = conn.execute("SELECT title, description, tags FROM videos WHERE id = ?", (s["video_id"],)).fetchone()
    if not v:
        raise ActionError("This video is no longer in the hub.")
    return {"title": v["title"], "description": v["description"], "tags": parse_tags(v["tags"])}


def editable_problem(conn, s) -> Optional[str]:
    """Why the target can't change in the hub any more, or None."""
    if s["draft_id"]:
        d = conn.execute("SELECT status FROM drafts WHERE id = ?", (s["draft_id"],)).fetchone()
        if not d:
            return "This draft no longer exists."
        if d["status"] != "ready":
            return "This draft was already added to the queue; change the video in the channel's queue instead."
        return None
    v = conn.execute("SELECT status, youtube_video_id FROM videos WHERE id = ?", (s["video_id"],)).fetchone()
    if not v:
        return "This video is no longer in the hub."
    if v["youtube_video_id"] or v["status"] not in LOCAL_STATUSES:
        return f"This video is {v['status']} and already on YouTube; its metadata is changed on YouTube, with approval."
    return None


def preview(conn, s, title: str, description: str, tags: List[str]) -> Dict[str, Any]:
    """Before and after, each as the upload would send it, with any limit problems of the new version."""
    prefs = channel_setup.defaults(conn, s["channel_id"])
    before_raw = current(conn, s)
    before = upload_metadata(prefs, **before_raw)
    after = upload_metadata(prefs, title, description, tags)
    return {
        "before": before, "after": after, "before_size": measure(before), "after_size": measure(after),
        "changed": [f for f in ("title", "description", "tags") if before_raw[f] != {"title": title, "description": description, "tags": tags}[f]],
        "problems": limit_problems(after),
        "footer": prefs.get("description_footer", ""), "default_tags": prefs.get("default_tags", []),
    }


def apply(conn, s, title: str, description: str, tags_text: str) -> Dict[str, Any]:
    """Write the approved title, description and tags to the target and keep a backup for Undo."""
    blocked = editable_problem(conn, s)
    if blocked:
        raise ActionError(blocked)
    if s["status"] not in ("ready", "applied"):
        raise ActionError("These suggestions aren't ready.")
    title, description = yt.clean_text(" ".join((title or "").split())), yt.clean_text((description or "").replace("\r\n", "\n"))
    tags = parse_tags(tags_text)
    if len(description) > 20000 or len(tags_text or "") > 5000:
        raise ActionError("That's far over YouTube's limits.")
    check = preview(conn, s, title, description, tags)
    if check["problems"]:
        raise ActionError(" ".join(check["problems"]))
    if not check["changed"]:
        raise ActionError("Nothing changed: this is what the video already has.")
    before = current(conn, s)
    new = {"title": title, "description": description, "tags": tags}
    _write(conn, s, new)
    # A second Apply keeps the very first backup, so Undo always returns to the original.
    backup = s["before_json"] if s["status"] == "applied" and s["before_json"] else json.dumps(before, ensure_ascii=False)
    conn.execute("UPDATE video_suggestions SET status = 'applied', before_json = ?, applied_json = ?, applied_at = ? WHERE id = ?",
                 (backup, json.dumps(new, ensure_ascii=False), timeutil.fmt(timeutil.now_local()), s["id"]))
    return check


def undo(conn, s) -> None:
    if s["status"] != "applied" or not s["before_json"]:
        raise ActionError("There's nothing to undo.")
    blocked = editable_problem(conn, s)
    if blocked:
        raise ActionError(blocked)
    if current(conn, s) != json.loads(s["applied_json"]):
        raise ActionError("The title, description or tags were changed again after Apply, so Undo would lose that edit. Change them by hand instead.")
    _write(conn, s, json.loads(s["before_json"]))
    conn.execute("UPDATE video_suggestions SET status = 'ready', before_json = NULL, applied_json = NULL, applied_at = NULL WHERE id = ?", (s["id"],))


def _write(conn, s, meta: Dict[str, Any]) -> None:
    if s["draft_id"]:
        draft, row, rows = _draft_row(conn, s)
        changed = dict(row, youtube_title=meta["title"], youtube_description=meta["description"], youtube_tags=", ".join(meta["tags"]))
        checked = read_rows([changed], get_spec(draft["niche"]), first_row=s["draft_row"])
        if not checked.ok:
            raise ActionError("; ".join(f"{e['column']}: {e['message']}" for e in checked.errors))
        rows[s["draft_row"] - 1] = changed
        conn.execute("UPDATE drafts SET rows_json = ? WHERE id = ?", (json.dumps(rows, ensure_ascii=False), s["draft_id"]))
    else:
        conn.execute("UPDATE videos SET title = ?, description = ?, tags = ? WHERE id = ?",
                     (meta["title"], meta["description"], ", ".join(meta["tags"]), s["video_id"]))


def _draft_row(conn, s):
    draft = conn.execute("SELECT niche, rows_json FROM drafts WHERE id = ?", (s["draft_id"],)).fetchone()
    if not draft:
        raise ActionError("This draft no longer exists.")
    rows = json.loads(draft["rows_json"] or "[]")
    if not 1 <= (s["draft_row"] or 0) <= len(rows):
        raise ActionError("This video is no longer in the draft.")
    return draft, rows[s["draft_row"] - 1], rows
