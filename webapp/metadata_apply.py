"""Changing a video's title, description and tags: limit checks, a before/after preview, backup and Undo.

A change targets one of three things:
- one row of a Gemini draft, or a hub video that isn't on YouTube yet: changed in the hub
  only, it goes out with the upload. The checks count what the upload really sends: the
  channel's description footer and default tags are added then (youtube_sync.upload_now).
- a video already on YouTube (a suggestion from the channel analysis): changed on YouTube
  with videos.update, snippet part only, so privacy and Made for Kids are never touched.
  Each Apply re-reads the live video first, refuses if it changed since the preview, keeps
  the old values in metadata_changes (one row per field), and can be rolled back.
Nothing changes anywhere without the user's explicit approval in the UI.
"""

import datetime as dt
import json
import uuid
from typing import Any, Dict, List, Optional

from content_templates import get_spec
from content_templates.excel import read_rows
from publishing import youtube as yt
from webapp import channel_setup, timeutil
from webapp.queue import ActionError

LOCAL_STATUSES = ("ready", "rendered", "failed")  # hub videos whose metadata can still change before upload
RECENT_DAYS = 7                                   # changing a video again sooner makes its results impossible to measure
EDIT_COST = 1 + yt.WRITE_COST                     # the live re-read plus videos.update
FIELDS = ("title", "description", "tags")


class RecentChange(ActionError):
    """The video's metadata changed on YouTube less than RECENT_DAYS ago; Apply needs a second confirmation."""


def is_remote(s) -> bool:
    """A suggestion from the channel analysis, for a video that is on YouTube."""
    return bool(s["context_json"]) if "context_json" in s.keys() else False


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
    """The target's title, description and tags: in the hub, or for a YouTube video as last read from YouTube."""
    if is_remote(s):
        live = json.loads(s["context_json"])["live"]
        return {"title": live["title"], "description": live["description"], "tags": list(live["tags"])}
    if s["draft_id"]:
        row = _draft_row(conn, s)[1]
        return {"title": row.get("youtube_title", "") or "", "description": row.get("youtube_description", "") or "",
                "tags": parse_tags(row.get("youtube_tags", "") or "")}
    v = conn.execute("SELECT title, description, tags FROM videos WHERE id = ?", (s["video_id"],)).fetchone()
    if not v:
        raise ActionError("This video is no longer in the hub.")
    return {"title": v["title"], "description": v["description"], "tags": parse_tags(v["tags"])}


def editable_problem(conn, s) -> Optional[str]:
    """Why the target can't be changed any more, or None."""
    if is_remote(s):
        row = conn.execute("SELECT v.youtube_video_id, c.connection, c.is_mock FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?",
                           (s["video_id"],)).fetchone()
        if not row or not row["youtube_video_id"]:
            return "This video is no longer in the hub; sync the channel and run the analysis again."
        if row["is_mock"]:
            return "This is a mock channel; nothing is sent to YouTube."
        if row["connection"] != "connected":
            return "This channel's YouTube sign-in has expired. Reconnect it in Settings, then apply."
        return None
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
    """Before and after, each as YouTube will get it, with any limit problems of the new version.
    For a video not uploaded yet that includes the channel's footer and default tags."""
    prefs = {} if is_remote(s) else channel_setup.defaults(conn, s["channel_id"])
    before_raw = current(conn, s)
    before = upload_metadata(prefs, **before_raw)
    after = upload_metadata(prefs, title, description, tags)
    return {
        "before": before, "after": after, "before_size": measure(before), "after_size": measure(after),
        "changed": [f for f in ("title", "description", "tags") if before_raw[f] != {"title": title, "description": description, "tags": tags}[f]],
        "problems": limit_problems(after),
        "footer": prefs.get("description_footer", ""), "default_tags": prefs.get("default_tags", []),
    }


def _clean_input(title: str, description: str, tags_text: str):
    if len(description or "") > 20000 or len(tags_text or "") > 5000 or len(title or "") > 1000:
        raise ActionError("That's far over YouTube's limits.")
    return yt.clean_text(" ".join((title or "").split())), yt.clean_text((description or "").replace("\r\n", "\n")), parse_tags(tags_text)


def apply(conn, s, title: str, description: str, tags_text: str, confirm_recent: bool = False, services=None) -> Dict[str, Any]:
    """Write the approved title, description and tags to the target and keep a backup for Undo."""
    blocked = editable_problem(conn, s)
    if blocked:
        raise ActionError(blocked)
    if s["status"] not in ("ready", "applied"):
        raise ActionError("These suggestions aren't ready.")
    title, description, tags = _clean_input(title, description, tags_text)
    check = preview(conn, s, title, description, tags)
    if check["problems"]:
        raise ActionError(" ".join(check["problems"]))
    if not check["changed"]:
        raise ActionError("Nothing changed: this is what the video already has.")
    if is_remote(s):
        return _apply_remote(conn, s, {"title": title, "description": description, "tags": tags}, check, confirm_recent, services)
    before = current(conn, s)
    new = {"title": title, "description": description, "tags": tags}
    _write(conn, s, new)
    # A second Apply keeps the very first backup, so Undo always returns to the original.
    backup = s["before_json"] if s["status"] == "applied" and s["before_json"] else json.dumps(before, ensure_ascii=False)
    conn.execute("UPDATE video_suggestions SET status = 'applied', before_json = ?, applied_json = ?, applied_at = ? WHERE id = ?",
                 (backup, json.dumps(new, ensure_ascii=False), timeutil.fmt(timeutil.now_local()), s["id"]))
    return check


def undo(conn, s, services=None) -> None:
    if is_remote(s):
        if not s["change_group"]:
            raise ActionError("There's nothing to roll back.")
        rollback(conn, s["change_group"], services)
        return
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


# ---------- videos on YouTube ----------

def recent_change(conn, youtube_video_id: str) -> Optional[Dict[str, Any]]:
    """The latest change on YouTube to this video within RECENT_DAYS, applied or rolled back."""
    since = timeutil.fmt(timeutil.now_local() - dt.timedelta(days=RECENT_DAYS))
    row = conn.execute(
        "SELECT change_group, action, created_at FROM metadata_changes WHERE youtube_video_id = ? AND status IN ('applied', 'rolled_back') "
        "AND created_at >= ? ORDER BY created_at DESC, id DESC LIMIT 1", (youtube_video_id, since)).fetchone()
    return dict(row) if row else None


def _services(conn, channel_id: int):
    from webapp import youtube_sync

    try:
        return youtube_sync._services(conn, channel_id)
    except yt.YouTubeError as e:
        raise ActionError(str(e))


def _youtube_error(e: yt.YouTubeError) -> ActionError:
    if isinstance(e, yt.QuotaExceeded):
        return ActionError("YouTube's daily API quota is used up, so nothing was changed. Try again after midnight Pacific time.")
    return ActionError(f"Nothing was changed on YouTube: {e}")


def _read_live(conn, youtube, youtube_id: str) -> Dict[str, Any]:
    from webapp import youtube_sync

    try:
        live = yt.video_details(youtube, [youtube_id]).get(youtube_id)
    except yt.YouTubeError as e:
        raise _youtube_error(e)
    finally:
        youtube_sync._add_quota(conn, 1)
    if not live:
        raise ActionError("YouTube no longer has this video; it may have been deleted in Studio.")
    return live


def _same(live: Dict[str, Any], meta: Dict[str, Any]) -> bool:
    return all(live[f] == meta[f] for f in ("title", "description")) and list(live["tags"]) == list(meta["tags"])


def _store_live(conn, s, live: Dict[str, Any], change_group: Optional[str] = None, status: Optional[str] = None) -> None:
    """Remember what's live on YouTube now, so the next preview starts from it."""
    context = json.loads(s["context_json"])
    context["live"] = {**context["live"], **{k: live[k] for k in FIELDS}}
    conn.execute("UPDATE video_suggestions SET context_json = ?, change_group = COALESCE(?, change_group), status = COALESCE(?, status) WHERE id = ?",
                 (json.dumps(context, ensure_ascii=False), change_group, status, s["id"]))


def _log(conn, group: str, action: str, row: Dict[str, Any], field_name: str, old, new, status: str, now: str) -> None:
    conn.execute(
        "INSERT INTO metadata_changes (change_group, action, channel_id, video_id, youtube_video_id, suggestion_id, field, old_value, new_value, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (group, action, row["channel_id"], row["video_id"], row["youtube_video_id"], row["suggestion_id"], field_name,
         _encode(field_name, old), _encode(field_name, new), status, now))


def _apply_remote(conn, s, new: Dict[str, Any], check: Dict[str, Any], confirm_recent: bool, services) -> Dict[str, Any]:
    from webapp import youtube_sync

    youtube_id = conn.execute("SELECT youtube_video_id FROM videos WHERE id = ?", (s["video_id"],)).fetchone()[0]
    recent = recent_change(conn, youtube_id)
    if recent and not confirm_recent:
        raise RecentChange(f"This video's metadata was changed on {recent['created_at'].replace('T', ' ')}, less than {RECENT_DAYS} days ago. "
                           "Changing it again so soon makes it impossible to tell which change helped. Tick \"Change it anyway\" to go ahead.")
    youtube, _ = services or _services(conn, s["channel_id"])
    live = _read_live(conn, youtube, youtube_id)
    if not _same(live, current(conn, s)):
        _store_live(conn, s, live)
        conn.commit()
        raise ActionError("The video was changed on YouTube since this preview was made (in Studio?). "
                          "The preview now shows what's live; check it and apply again.")

    group, now = uuid.uuid4().hex, timeutil.fmt(timeutil.now_local())
    who = {"channel_id": s["channel_id"], "video_id": s["video_id"], "youtube_video_id": youtube_id, "suggestion_id": s["id"]}
    for f in check["changed"]:
        _log(conn, group, "apply", who, f, live[f], new[f], "pending", now)
    conn.commit()  # the backup is on disk before YouTube is touched
    try:
        saved = yt.update_video_metadata(youtube, live, new["title"], new["description"], new["tags"])
    except yt.YouTubeError as e:
        conn.execute("UPDATE metadata_changes SET status = 'failed', error = ? WHERE change_group = ?", (str(e)[:500], group))
        youtube_sync._add_quota(conn, yt.WRITE_COST)
        conn.commit()
        raise _youtube_error(e)
    youtube_sync._add_quota(conn, yt.WRITE_COST)
    conn.execute("UPDATE metadata_changes SET status = 'applied' WHERE change_group = ?", (group,))
    conn.execute("UPDATE videos SET title = ?, description = ?, tags = ? WHERE id = ?",
                 (saved["title"], saved["description"], ", ".join(saved["tags"]), s["video_id"]))
    conn.execute("UPDATE video_suggestions SET before_json = ?, applied_json = ?, applied_at = ? WHERE id = ?",
                 (json.dumps({k: live[k] for k in FIELDS}, ensure_ascii=False), json.dumps(saved, ensure_ascii=False), now, s["id"]))
    _store_live(conn, s, saved, group, "applied")
    return {**check, "change_group": group}


def rollback(conn, change_group: str, services=None) -> None:
    """Put back on YouTube what a change replaced, if nobody has edited the video since."""
    from webapp import youtube_sync

    rows = [dict(r) for r in conn.execute("SELECT * FROM metadata_changes WHERE change_group = ? AND action = 'apply'", (change_group,))]
    if not rows:
        raise ActionError("That change wasn't found.")
    if rows[0]["status"] == "rolled_back":
        raise ActionError("This change was already rolled back.")
    if rows[0]["status"] != "applied":
        raise ActionError("This change never reached YouTube, so there's nothing to roll back.")
    newer = conn.execute("SELECT 1 FROM metadata_changes WHERE youtube_video_id = ? AND action = 'apply' AND status = 'applied' AND id > ?",
                         (rows[0]["youtube_video_id"], max(r["id"] for r in rows))).fetchone()
    if newer:
        raise ActionError("A newer change to this video is live; roll that one back first.")
    c = conn.execute("SELECT connection, is_mock FROM channels WHERE id = ?", (rows[0]["channel_id"],)).fetchone()
    if not c or c["is_mock"] or c["connection"] != "connected":
        raise ActionError("This channel's YouTube sign-in has expired. Reconnect it in Settings, then roll back.")

    youtube, _ = services or _services(conn, rows[0]["channel_id"])
    live = _read_live(conn, youtube, rows[0]["youtube_video_id"])
    for r in rows:
        if _encode(r["field"], live[r["field"]]) != r["new_value"]:
            raise ActionError(f"The {r['field']} was changed on YouTube after this change, so rolling back would overwrite that edit. "
                              "Change it in Studio instead.")
    old = {k: live[k] for k in FIELDS}
    for r in rows:
        old[r["field"]] = _decode(r["field"], r["old_value"])
    try:
        saved = yt.update_video_metadata(youtube, live, old["title"], old["description"], old["tags"])
    except yt.YouTubeError as e:
        youtube_sync._add_quota(conn, yt.WRITE_COST)
        raise _youtube_error(e)
    youtube_sync._add_quota(conn, yt.WRITE_COST)
    group, now = uuid.uuid4().hex, timeutil.fmt(timeutil.now_local())
    for r in rows:
        _log(conn, group, "rollback", r, r["field"], _decode(r["field"], r["new_value"]), _decode(r["field"], r["old_value"]), "applied", now)
    conn.execute("UPDATE metadata_changes SET status = 'rolled_back', rolled_back_at = ?, rolled_back_by = ? WHERE change_group = ? AND action = 'apply'",
                 (now, group, change_group))
    if rows[0]["video_id"]:
        conn.execute("UPDATE videos SET title = ?, description = ?, tags = ? WHERE id = ?",
                     (saved["title"], saved["description"], ", ".join(saved["tags"]), rows[0]["video_id"]))
    s = conn.execute("SELECT * FROM video_suggestions WHERE change_group = ?", (change_group,)).fetchone()
    if s:
        conn.execute("UPDATE video_suggestions SET before_json = NULL, applied_json = NULL, applied_at = NULL WHERE id = ?", (s["id"],))
        _store_live(conn, s, saved, None, "ready")


def _encode(field_name: str, value) -> str:
    return json.dumps(list(value), ensure_ascii=False) if field_name == "tags" else str(value)


def _decode(field_name: str, value: str):
    return json.loads(value) if field_name == "tags" else value


def change_log(conn, channel_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Every change on YouTube for the channel, newest first, one entry per Apply or Rollback."""
    groups: Dict[str, Dict[str, Any]] = {}
    for r in conn.execute(
            "SELECT m.*, v.title video_title FROM metadata_changes m LEFT JOIN videos v ON v.id = m.video_id "
            "WHERE m.channel_id = ? ORDER BY m.created_at DESC, m.id DESC", (channel_id,)):
        if r["change_group"] not in groups and len(groups) >= limit:
            break
        g = groups.setdefault(r["change_group"], {"group": r["change_group"], "action": r["action"], "status": r["status"],
                                                   "created_at": r["created_at"], "youtube_video_id": r["youtube_video_id"],
                                                   "video_title": r["video_title"], "error": r["error"], "fields": []})
        g["fields"].append({"field": r["field"], "old": _decode(r["field"], r["old_value"]), "new": _decode(r["field"], r["new_value"])})
    out = list(groups.values())
    seen = set()
    for g in out:  # only the newest applied change per video can be rolled back
        live = g["action"] == "apply" and g["status"] == "applied"
        g["can_rollback"] = live and g["youtube_video_id"] not in seen
        if live:
            seen.add(g["youtube_video_id"])
    return out
