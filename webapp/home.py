"""Extra read-only data for the dashboard's AI Optimizer and "Drafts ready to improve" cards."""

import json
from typing import Any, Dict, List, Optional


def extras(conn, sc: Dict[str, Any]) -> Dict[str, Any]:
    ids: Optional[List[int]] = sc["ids"]
    where, args = ("", []) if ids is None else (f" AND c.id IN ({','.join('?' * len(ids))})" if ids else " AND 0", list(ids or []))
    return {"optimizer": _optimizer(conn, sc, where, args), "improve": _improve(conn, where, args)}


def _optimizer(conn, sc, where: str, args: list) -> Dict[str, Any]:
    """The selected channel's latest analysis, or every analysed channel's score."""
    if sc["channel"]:
        a = conn.execute("SELECT * FROM channel_audits WHERE channel_id = ? AND status = 'ready' ORDER BY id DESC LIMIT 1", (sc["channel"]["id"],)).fetchone()
        live = conn.execute("SELECT youtube_channel_id, connection FROM channels WHERE id = ?", (sc["channel"]["id"],)).fetchone()
        if not a:
            return {"mode": "none", "channel": sc["channel"], "can_run": bool(live and live["youtube_channel_id"] and live["connection"] == "connected")}
        report = json.loads(a["report_json"])
        problems = [f for f in report["findings"] if f["severity"] != "info"]
        good = [f for f in report["findings"] if f["severity"] == "info" and not f["title"].startswith("Not enough data")]
        return {"mode": "one", "channel": sc["channel"], "audit": dict(a), "problems": problems[:3], "good": good[:1],
                "headline": problems[0]["title"] if problems else "No problems found by the checks."}
    rows = conn.execute(
        "SELECT c.id, c.name, a.id audit_id, a.score, a.finished_at FROM channels c JOIN channel_audits a ON a.id = "
        "(SELECT MAX(id) FROM channel_audits WHERE channel_id = c.id AND status = 'ready') WHERE 1=1" + where + " ORDER BY a.score", args).fetchall()
    return {"mode": "all", "channels": [dict(r) for r in rows]}


def _improve(conn, where: str, args: list) -> List[Dict[str, Any]]:
    """Gemini drafts waiting for review and queued videos not on YouTube yet, newest first."""
    drafts = [{"kind": "draft", "title": r["topic"], "sub": f"Gemini draft · {r['count']} video{'' if r['count'] == 1 else 's'} · {r['channel']}",
               "href": f"/drafts/{r['id']}"} for r in conn.execute(
        "SELECT d.id, d.topic, d.count, c.name channel FROM drafts d JOIN channels c ON c.id = d.channel_id WHERE d.status = 'ready'" + where +
        " ORDER BY d.id DESC LIMIT 3", args)]
    videos = [{"kind": "video", "title": r["title"], "sub": f"Not on YouTube yet · {r['channel']}", "href": f"/videos/{r['id']}/suggestions"}
              for r in conn.execute(
        "SELECT v.id, v.title, c.name channel FROM videos v JOIN channels c ON c.id = v.channel_id "
        "WHERE v.status IN ('ready', 'rendered') AND v.youtube_video_id IS NULL AND v.is_mock = 0" + where +
        " AND NOT EXISTS (SELECT 1 FROM video_suggestions s WHERE s.video_id = v.id AND s.status = 'applied') ORDER BY v.publish_at LIMIT 3", args)]
    return (drafts + videos)[:4]
