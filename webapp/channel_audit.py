"""AI Optimizer: the channel analysis ("Run analysis" on a channel page).

One run, in the background:
1. sync the channel (daily stats and video list, as the Sync button does), and measure earlier
   changes made on YouTube: each video's views 7 days before against 7 days after;
2. read per-video analytics, traffic sources and the Shorts/long-form split (Analytics API,
   read-only) and every video's live metadata (Data API, 1 unit per 50 videos);
3. run the rule-based checks (webapp.optimizer_checks) and save the report;
4. ask Gemini, one request per video, for suggestions on the weakest videos (10 by default),
   sent only those findings and numbers. Without a Gemini key the report is still saved.
Nothing is changed on YouTube here; changes need approval (webapp.metadata_apply).
"""

import datetime as dt
import json
import logging
import statistics
import threading
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from publishing import youtube as yt
from webapp import db, optimizer, optimizer_checks as checks, timeutil, youtube_sync
from webapp.queue import ActionError

logger = logging.getLogger(__name__)

PERIOD_DAYS = 28
VIDEO_DAYS = 90          # per-video numbers cover the last 90 days, so small channels have something to judge
DEFAULT_VIDEOS = 10
VIDEO_LIMITS = (10, 0)   # 0 = every public video


def start(conn, channel_id: int, video_limit: int = DEFAULT_VIDEOS) -> int:
    c = conn.execute("SELECT is_mock, connection, youtube_channel_id FROM channels WHERE id = ?", (channel_id,)).fetchone()
    if not c:
        raise ActionError("Channel not found.")
    if c["is_mock"] or not c["youtube_channel_id"]:
        raise ActionError("Only a real channel connected to YouTube can be analysed.")
    if c["connection"] != "connected":
        raise ActionError("This channel's YouTube sign-in has expired. Reconnect it in Settings first.")
    if video_limit not in VIDEO_LIMITS:
        raise ActionError("Pick how many videos to write suggestions for.")
    if conn.execute("SELECT 1 FROM channel_audits WHERE channel_id = ? AND status = 'running'", (channel_id,)).fetchone():
        raise ActionError("An analysis of this channel is already running.")
    audit_id = conn.execute("INSERT INTO channel_audits (channel_id, status, period_days, video_limit, started_at) VALUES (?,?,?,?,?)",
                            (channel_id, "running", PERIOD_DAYS, video_limit, timeutil.fmt(timeutil.now_local()))).lastrowid
    conn.commit()
    threading.Thread(target=run, args=(audit_id,), daemon=True).start()
    return audit_id


def gather(conn, channel_id: int, services) -> Dict[str, Any]:
    """Everything the checks need, read from YouTube once."""
    youtube, analytics = services
    youtube_sync.sync_channel(conn, channel_id, services=services)
    c = conn.execute("SELECT timezone FROM channels WHERE id = ?", (channel_id,)).fetchone()
    today = timeutil.now_local().date()
    end = today - dt.timedelta(days=1)  # today's numbers aren't complete yet
    start = end - dt.timedelta(days=PERIOD_DAYS - 1)
    per_video = yt.video_report(analytics, end - dt.timedelta(days=VIDEO_DAYS - 1), end)
    traffic = yt.traffic_sources(analytics, start, end)
    try:
        content = yt.content_types(analytics, start, end)
    except yt.YouTubeError:  # not every channel gets this split; the video lengths still tell Shorts apart
        content = {}
    reach = yt.reach_metrics(analytics, start, end)

    rows = conn.execute("SELECT id, youtube_video_id, content_json FROM videos WHERE channel_id = ? AND youtube_video_id IS NOT NULL",
                        (channel_id,)).fetchall()
    hub_ids = {r["youtube_video_id"]: r["id"] for r in rows}
    live = yt.video_details(youtube, list(hub_ids))
    youtube_sync._add_quota(conn, max(1, -(-len(hub_ids) // 50)))
    try:
        playlists: Optional[int] = len(yt.list_playlists(youtube))
        youtube_sync._add_quota(conn, 1)
    except yt.YouTubeError:
        playlists = None

    videos = []
    for yid, info in live.items():
        stats = per_video.get(yid, {})
        is_short = info["duration_s"] is not None and info["duration_s"] <= optimizer.SHORT_MAX_SECONDS
        videos.append({
            "youtube_id": yid, "video_id": hub_ids.get(yid), "title": info["title"], "description": info["description"],
            "tags": info["tags"], "published_at": info["published_at"], "duration_s": info["duration_s"], "is_short": is_short,
            "privacy": info["privacy"], "made_for_kids": info["made_for_kids"], "lifetime_views": info["views"],
            "views": stats.get("views", 0), "watch_minutes": stats.get("watch_minutes", 0), "avg_view_s": stats.get("avg_view_s"),
            "avg_view_pct": stats.get("avg_view_pct"), "likes": stats.get("likes", 0), "shares": stats.get("shares", 0),
            "subs_gained": stats.get("subs_gained", 0),
        })
        if stats.get("avg_view_pct") is not None:
            conn.execute("UPDATE videos SET avg_view_pct = ? WHERE id = ?", (stats["avg_view_pct"], hub_ids[yid]))
    daily = [dict(r) for r in conn.execute(
        "SELECT date, views, watch_minutes, subs_gained, subs_lost FROM daily_stats WHERE channel_id = ? AND date >= ? ORDER BY date",
        (channel_id, (today - dt.timedelta(days=2 * PERIOD_DAYS)).isoformat()))]
    return {"today": today, "period": PERIOD_DAYS, "videos": videos, "traffic": traffic, "content": content, "daily": daily,
            "playlists": playlists, "reach": reach, "tz": ZoneInfo(c["timezone"]), "live": live}


MEASURE_DAYS = 7         # views this many days before a change against as many after
DATA_LAG_DAYS = 3        # YouTube's per-day numbers settle after about 3 days
MEASURE_WINDOW = 90      # changes older than this aren't measured again


def measure_changes(conn, channel_id: int, analytics, today: dt.date) -> List[Dict[str, Any]]:
    """For each change made on YouTube, the video's views in the 7 days before against the 7 days after."""
    last_day = today - dt.timedelta(days=DATA_LAG_DAYS)
    groups = conn.execute(
        "SELECT change_group, youtube_video_id, MIN(created_at) created_at, MIN(status) status, GROUP_CONCAT(field, ', ') fields "
        "FROM metadata_changes WHERE channel_id = ? AND action = 'apply' AND status IN ('applied', 'rolled_back') AND created_at >= ? "
        "GROUP BY change_group ORDER BY created_at DESC",
        (channel_id, timeutil.fmt(timeutil.now_local() - dt.timedelta(days=MEASURE_WINDOW)))).fetchall()
    out = []
    for g in groups:
        changed = timeutil.parse(g["created_at"]).date()
        title = conn.execute("SELECT title FROM videos WHERE youtube_video_id = ?", (g["youtube_video_id"],)).fetchone()
        row = {"group": g["change_group"], "youtube_video_id": g["youtube_video_id"], "video_title": title[0] if title else g["youtube_video_id"],
               "changed_at": g["created_at"], "fields": g["fields"], "rolled_back": g["status"] == "rolled_back",
               "before": None, "after": None, "change_pct": None, "state": "waiting"}
        after_end = changed + dt.timedelta(days=MEASURE_DAYS)
        if after_end > last_day:
            row["ready_on"] = (after_end + dt.timedelta(days=DATA_LAG_DAYS)).isoformat()
            out.append(row)
            continue
        try:
            views = yt.video_daily_views(analytics, g["youtube_video_id"], changed - dt.timedelta(days=MEASURE_DAYS), after_end)
        except yt.YouTubeError as e:
            row.update(state="unreadable", error=str(e)[:200])
            out.append(row)
            continue
        before = sum(v for d, v in views.items() if d < changed.isoformat())
        after = sum(v for d, v in views.items() if d > changed.isoformat())
        row.update(before=before, after=after, state="measured",
                   change_pct=round((after - before) / before * 100, 1) if before else None)
        out.append(row)
    return out


def compare(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Two saved analyses side by side: metric changes, and findings fixed, new and still open."""
    a, b = old["report"], new["report"]
    metrics = []
    for key, label, better in (("views", "Views (28 days)", "up"), ("avg_view_pct", "Average % viewed", "up"),
                               ("recommended_pct", "From recommendations %", "up"), ("search_pct", "From search %", "up"),
                               ("likes_per_1000", "Likes per 1,000 views", "up")):
        x, y = a["numbers"].get(key), b["numbers"].get(key)
        diff = None if x is None or y is None else round(y - x, 1)
        metrics.append({"label": label, "old": x, "new": y, "diff": diff,
                        "good": None if not diff else (diff > 0) == (better == "up")})
    score_diff = None if old["score"] is None or new["score"] is None else new["score"] - old["score"]
    metrics.insert(0, {"label": "Health score", "old": old["score"], "new": new["score"], "diff": score_diff,
                       "good": None if not score_diff else score_diff > 0})
    problems = lambda r: {f["key"]: f for f in r["findings"] if f["severity"] != "info"}
    pa, pb = problems(a), problems(b)
    return {
        "metrics": metrics,
        "fixed": [pa[k] for k in pa if k not in pb],
        "new": [pb[k] for k in pb if k not in pa],
        "open": [pb[k] for k in pb if k in pa],
        "days_apart": (timeutil.parse(new["started_at"]).date() - timeutil.parse(old["started_at"]).date()).days,
    }


def history(conn, channel_id: int, limit: int = 12) -> List[Dict[str, Any]]:
    out = []
    for a in conn.execute("SELECT * FROM channel_audits WHERE channel_id = ? ORDER BY id DESC LIMIT ?", (channel_id, limit)):
        r = json.loads(a["report_json"]) if a["report_json"] else {}
        out.append({**dict(a), "numbers": r.get("numbers", {}), "problems": sum(1 for f in r.get("findings", []) if f["severity"] != "info")})
    return out


def previous(conn, audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The last finished analysis of the same channel before this one."""
    a = conn.execute("SELECT id FROM channel_audits WHERE channel_id = ? AND status = 'ready' AND id < ? ORDER BY id DESC LIMIT 1",
                     (audit["channel_id"], audit["id"])).fetchone()
    return latest_ready(conn, a["id"]) if a else None


def latest_ready(conn, audit_id: int) -> Optional[Dict[str, Any]]:
    a = conn.execute("SELECT * FROM channel_audits WHERE id = ? AND status = 'ready'", (audit_id,)).fetchone()
    if not a:
        return None
    return {**dict(a), "report": json.loads(a["report_json"])}


def run(audit_id: int, services=None, client=None) -> None:
    conn = db.connect()
    suggestion_ids: List[int] = []
    try:
        a = conn.execute("SELECT * FROM channel_audits WHERE id = ?", (audit_id,)).fetchone()
        try:
            services = services or youtube_sync._services(conn, a["channel_id"])
            data = gather(conn, a["channel_id"], services)
            changes = measure_changes(conn, a["channel_id"], services[1], data["today"])
        except yt.QuotaExceeded:
            raise ActionError("YouTube's daily API quota is used up. Run the analysis again after midnight Pacific time.")
        except yt.YouTubeError as e:
            raise ActionError(f"Couldn't read the channel from YouTube: {e}")
        result = checks.run_checks(data)
        videos = data["videos"]
        rated = checks.judged(videos)
        channel_pct = result["numbers"]["avg_view_pct"]
        median_views = statistics.median([v["views"] for v in videos]) if videos else 0
        picked = checks.weakest(videos, data["today"], a["video_limit"])
        channel_findings = [f"{f['title']}: {f['detail']}"[:300] for f in result["findings"] if f["severity"] != "info"][:5]
        report = {
            "findings": result["findings"], "numbers": result["numbers"], "traffic": data["traffic"], "content": data["content"],
            "reach": data["reach"], "playlists": data["playlists"], "period": PERIOD_DAYS, "video_days": VIDEO_DAYS,
            "videos": [{k: v[k] for k in ("youtube_id", "video_id", "title", "is_short", "views", "lifetime_views", "avg_view_pct", "likes",
                                         "shares", "subs_gained", "published_at", "made_for_kids")} for v in videos],
            "picked": [v["youtube_id"] for v in picked], "rated_videos": len(rated), "change_results": changes,
        }
        model, gemini_note = None, ""
        try:
            model = optimizer._model(conn)
        except ActionError as e:
            gemini_note = f"{e} The rule-based report is ready; suggestions need Gemini."
        report["gemini_note"] = gemini_note
        conn.execute("UPDATE channel_audits SET status = 'ready', score = ?, report_json = ?, finished_at = ? WHERE id = ?",
                     (result["score"], json.dumps(report, ensure_ascii=False, default=str), timeutil.fmt(timeutil.now_local()), audit_id))
        if model:
            for v in picked:
                if not v["video_id"]:
                    continue
                findings = checks.video_findings(v, channel_pct, median_views)
                suggestion_ids.append(optimizer.insert_remote(conn, audit_id, a["channel_id"], model, v["video_id"], data["live"][v["youtube_id"]],
                                                              v["is_short"], findings, channel_findings))
        conn.commit()
    except ActionError as e:
        conn.execute("UPDATE channel_audits SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                     (str(e)[:500], timeutil.fmt(timeutil.now_local()), audit_id))
    except Exception as e:
        logger.exception("Channel analysis %s failed", audit_id)
        conn.execute("UPDATE channel_audits SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                     (f"The analysis failed: {type(e).__name__}"[:500], timeutil.fmt(timeutil.now_local()), audit_id))
    finally:
        conn.commit()
        conn.close()
    if suggestion_ids:
        optimizer.run(suggestion_ids, client=client)


def load(conn, audit_id: int) -> Dict[str, Any]:
    a = conn.execute("SELECT * FROM channel_audits WHERE id = ?", (audit_id,)).fetchone()
    if not a:
        raise ActionError("Analysis not found.")
    out = dict(a)
    out["report"] = json.loads(a["report_json"]) if a["report_json"] else None
    out["suggestions"] = [optimizer.view(conn, s) for s in conn.execute(
        "SELECT * FROM video_suggestions WHERE audit_id = ? ORDER BY id", (audit_id,))]
    out["writing"] = sum(1 for s in out["suggestions"] if s["status"] == "generating")
    return out


def latest(conn, channel_id: int) -> Optional[Dict[str, Any]]:
    a = conn.execute("SELECT * FROM channel_audits WHERE channel_id = ? ORDER BY id DESC LIMIT 1", (channel_id,)).fetchone()
    if not a:
        return None
    out = dict(a)
    out["report"] = json.loads(a["report_json"]) if a["report_json"] else None
    return out
