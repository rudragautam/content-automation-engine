"""Read-side numbers for the dashboard, channel pages and analytics."""

import datetime as dt
from typing import Any, Dict, List, Optional, Sequence, Union

from content_templates.specs import NICHES
from webapp import timeutil

DAILY_QUOTA = 10_000
UPLOAD_COST = 1_600
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def niche_name(niche: str) -> str:
    return NICHES[niche].name if niche in NICHES else niche.replace("_", " ").title()


Channels = Optional[Union[int, Sequence[int]]]  # None = every channel, an ID, or a list of IDs


def _in(column: str, channels: Channels):
    """SQL fragment (starting with AND) that keeps only rows of the given channels."""
    if channels is None or channels == 0:
        return "", []
    ids = [channels] if isinstance(channels, int) else list(channels)
    if not ids:
        return " AND 0", []
    return f" AND {column} IN ({','.join('?' * len(ids))})", ids


def _period(days: int):
    today = timeutil.now_local().date()
    start = today - dt.timedelta(days=days)
    prev_start = start - dt.timedelta(days=days)
    return today, start, prev_start


def _sum_stats(conn, start, end, channels: Channels = None) -> Dict[str, int]:
    where, args = "date >= ? AND date < ?", [start.isoformat(), end.isoformat()]
    frag, ids = _in("channel_id", channels)
    where += frag
    args += ids
    row = conn.execute(
        f"SELECT COALESCE(SUM(views),0) v, COALESCE(SUM(watch_minutes),0) w, COALESCE(SUM(subs_gained - subs_lost),0) s FROM daily_stats WHERE {where}", args
    ).fetchone()
    hours = row["w"] / 60
    # Below 10 hours keep a decimal, so a new channel's 20 minutes isn't shown as 0.
    return {"views": row["v"], "watch_hours": round(hours, 1) if hours < 10 else round(hours), "net_subs": row["s"]}


def _delta(current: float, previous: float) -> Optional[float]:
    return None if not previous else round((current - previous) / previous * 100, 1)


def daily_series(conn, days: int, channels: Channels = None, metric: str = "views") -> List[Dict[str, Any]]:
    today, start, _ = _period(days)
    where, args = "date >= ? AND date < ?", [start.isoformat(), today.isoformat()]
    frag, ids = _in("channel_id", channels)
    where += frag
    args += ids
    column = {"views": "SUM(views)", "watch_hours": "SUM(watch_minutes) / 60.0", "net_subs": "SUM(subs_gained - subs_lost)"}[metric]
    rows = conn.execute(f"SELECT date, {column} value FROM daily_stats WHERE {where} GROUP BY date ORDER BY date", args).fetchall()
    return [{"date": r["date"], "value": round(r["value"] or 0, 1)} for r in rows]


def kpis(conn, days: int, channels: Channels = None) -> Dict[str, Any]:
    today, start, prev_start = _period(days)
    cur = _sum_stats(conn, start, today, channels)
    prev = _sum_stats(conn, prev_start, start, channels)
    frag, ids = _in("id", channels)
    subscribers = conn.execute(f"SELECT COALESCE(SUM(subscribers),0) FROM channels WHERE 1{frag}", ids).fetchone()[0]
    vid_where = "status = 'published' AND publish_at >= ? AND publish_at < ?"
    vid_args = [start.isoformat(), today.isoformat()]
    frag, ids = _in("channel_id", channels)
    vid_where += frag
    vid_args += ids
    published = conn.execute(f"SELECT COUNT(*) FROM videos WHERE {vid_where}", vid_args).fetchone()[0]
    return {
        "subscribers": subscribers,
        "views": cur["views"], "views_delta": _delta(cur["views"], prev["views"]),
        "watch_hours": cur["watch_hours"], "watch_delta": _delta(cur["watch_hours"], prev["watch_hours"]),
        "net_subs": cur["net_subs"], "subs_delta": _delta(cur["net_subs"], prev["net_subs"]),
        "published": published,
    }


def channel_rows(conn, days: int, channels: Channels = None) -> List[Dict[str, Any]]:
    today, start, prev_start = _period(days)
    now = timeutil.fmt(timeutil.now_local())
    rows = []
    frag, ids = _in("id", channels)
    for ch in conn.execute(f"SELECT * FROM channels WHERE 1{frag} ORDER BY subscribers DESC", ids).fetchall():
        cur = _sum_stats(conn, start, today, ch["id"])
        prev = _sum_stats(conn, prev_start, start, ch["id"])
        spark = [r["value"] for r in daily_series(conn, 28, ch["id"])]
        nxt = conn.execute(
            "SELECT MIN(publish_at) FROM videos WHERE channel_id = ? AND status IN ('scheduled','rendered','ready') AND publish_at > ?", (ch["id"], now)
        ).fetchone()[0]
        last = conn.execute(
            "SELECT MAX(publish_at) FROM videos WHERE channel_id = ? AND status IN ('scheduled','rendered','ready') AND publish_at > ?", (ch["id"], now)
        ).fetchone()[0]
        covered_days = (timeutil.parse(last).date() - today).days if last else 0
        rows.append({
            **dict(ch), "niche_name": niche_name(ch["niche"]),
            "views": cur["views"], "views_delta": _delta(cur["views"], prev["views"]),
            "watch_hours": cur["watch_hours"], "net_subs": cur["net_subs"],
            "spark": spark, "next_publish": nxt, "covered_days": covered_days,
        })
    return rows


def views_by_niche(conn, days: int, channels: Channels = None) -> List[Dict[str, Any]]:
    today, start, _ = _period(days)
    frag, ids = _in("s.channel_id", channels)
    rows = conn.execute(
        "SELECT c.niche, SUM(s.views) views FROM daily_stats s JOIN channels c ON c.id = s.channel_id "
        f"WHERE s.date >= ? AND s.date < ?{frag} GROUP BY c.niche ORDER BY views DESC", [start.isoformat(), today.isoformat(), *ids]
    ).fetchall()
    return [{"label": niche_name(r["niche"]), "value": r["views"]} for r in rows]


def top_videos(conn, days: int, channels: Channels = None, limit: int = 10) -> List[Dict[str, Any]]:
    today, start, _ = _period(days)
    where, args = "v.status = 'published' AND v.publish_at >= ?", [start.isoformat()]
    frag, ids = _in("v.channel_id", channels)
    where += frag
    args += ids
    rows = conn.execute(
        f"SELECT v.*, c.name channel_name FROM videos v JOIN channels c ON c.id = v.channel_id WHERE {where} ORDER BY v.views DESC LIMIT ?", args + [limit]
    ).fetchall()
    return [dict(r) for r in rows]


def timing_heatmap(conn, days: int, channels: Channels = None) -> Dict[str, Any]:
    """Average views per published video by weekday and publish hour."""
    today, start, _ = _period(days)
    where, args = "status = 'published' AND publish_at >= ?", [start.isoformat()]
    frag, ids = _in("channel_id", channels)
    where += frag
    args += ids
    cells: Dict[tuple, List[int]] = {}
    for r in conn.execute(f"SELECT publish_at, views FROM videos WHERE {where}", args):
        t = timeutil.parse(r["publish_at"])
        cells.setdefault((t.weekday(), t.hour), []).append(r["views"])
    hours = sorted({h for _, h in cells})
    grid = [[(round(sum(cells[(d, h)]) / len(cells[(d, h)])) if (d, h) in cells else None) for h in hours] for d in range(7)]
    counts = [[len(cells.get((d, h), [])) for h in hours] for d in range(7)]
    return {"rows": WEEKDAYS, "cols": [f"{h:02d}:00" for h in hours], "values": grid, "counts": counts}


def quota_today(conn) -> Dict[str, Any]:
    today = timeutil.now_local().date().isoformat()
    row = conn.execute("SELECT units FROM quota_usage WHERE date = ?", (today,)).fetchone()
    used = row[0] if row else 0
    return {"used": used, "limit": DAILY_QUOTA, "pct": round(used / DAILY_QUOTA * 100), "uploads_left": max(0, (DAILY_QUOTA - used) // UPLOAD_COST)}


def alerts(conn, channels: Channels = None) -> List[Dict[str, str]]:
    out = []
    frag, ids = _in("id", channels)
    for ch in conn.execute(f"SELECT id, name, connection FROM channels WHERE connection != 'connected'{frag}", ids):
        if ch["connection"] == "expired":
            out.append({"level": "critical", "text": f"{ch['name']}: YouTube sign-in expired. Uploads are paused until it is reconnected.", "href": f"/channels/{ch['id']}"})
        else:
            out.append({"level": "warning", "text": f"{ch['name']}: not connected to YouTube yet.", "href": f"/channels/{ch['id']}"})
    frag, ids = _in("c.id", channels)
    for v in conn.execute(f"SELECT v.id, v.title, v.error, c.name, c.id cid FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.status = 'failed'{frag}", ids):
        out.append({"level": "critical", "text": f"{v['name']}: “{v['title']}” failed. {v['error'] or ''}", "href": f"/channels/{v['cid']}#queue"})
    q = quota_today(conn)
    if q["pct"] >= 60:
        out.append({"level": "warning", "text": f"API quota {q['pct']}% used today; about {q['uploads_left']} more uploads fit.", "href": "/schedule"})
    return out


def low_queue(rows: List[Dict[str, Any]], min_days: int = 3) -> List[Dict[str, Any]]:
    return [r for r in rows if r["connection"] == "connected" and r["covered_days"] < min_days]
