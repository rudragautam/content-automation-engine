"""Content hub web app: dashboard, channels, schedule, content, audio, analytics."""

import datetime as dt
import json
import os
import re
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from content_templates import NICHES, workbook_bytes
from publishing.youtube import YouTubeError
from webapp import ai_drafts, analytics, db, mock, queue, timeutil, youtube_sync
from webapp.queue import ActionError

HERE = os.path.dirname(os.path.abspath(__file__))
RANGES = (7, 28, 90)
MAX_SHEET_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 60 * 1024 * 1024

@asynccontextmanager
async def lifespan(_app):
    db.init()
    with db.session() as conn:
        if os.environ.get("CONTENT_HUB_DEMO") == "1":  # demo channels only when asked for
            mock.seed(conn)
        # A render interrupted by a restart would otherwise stay "rendering" forever.
        conn.execute("UPDATE videos SET status = 'failed', error = 'Render interrupted by a restart; render again.' WHERE status = 'rendering'")
        conn.execute("UPDATE videos SET status = 'rendered', error = 'Upload interrupted by a restart; upload again.' WHERE status = 'uploading'")
        conn.execute("UPDATE drafts SET status = 'failed', error = 'Generation interrupted by a restart; generate again.' WHERE status = 'generating'")
    yield


app = FastAPI(title="Content Hub", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))


# ---------- template helpers ----------

def compact(n) -> str:
    if n is None:
        return "—"
    n = float(n)
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size:
            value = n / size
            return f"{value:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{n:,.0f}"


def when(value: str) -> str:
    if not value:
        return "—"
    t = timeutil.parse(value)
    today = timeutil.now_local().date()
    fallback = t.strftime("%a %d %b") if t.year == today.year else t.strftime("%d %b %Y")
    day = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get((t.date() - today).days, fallback)
    return f"{day}, {t.strftime('%H:%M')}"


templates.env.filters["compact"] = compact
templates.env.filters["when"] = when
templates.env.filters["signed"] = lambda n: f"{n:+,}"
# JSON for <script type="application/json"> blocks: "</" is escaped so the data can't close the tag.
templates.env.filters["tojson_safe"] = lambda v: Markup(json.dumps(v, ensure_ascii=False).replace("</", "<\\/"))
templates.env.globals["niche_name"] = analytics.niche_name
templates.env.globals["renderable"] = {n for n in NICHES if queue.can_render(n)}


def page(request: Request, name: str, **ctx):
    with db.session() as conn:
        ctx.setdefault("alert_count", len(analytics.alerts(conn)))
        ctx.setdefault("mock_count_global", conn.execute("SELECT COUNT(*) FROM channels WHERE is_mock = 1").fetchone()[0])
    active = ctx.pop("active_override", None) or name.split(".")[0]
    return templates.TemplateResponse(request, name, {"active": active, "ranges": RANGES, **ctx})


def days_param(days: int) -> int:
    return days if days in RANGES else 28


def error(e: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(e)}, status_code=status)


# ---------- pages ----------

@app.get("/")
def dashboard(request: Request, days: int = 28):
    days = days_param(days)
    with db.session() as conn:
        rows = analytics.channel_rows(conn, days)
        return page(
            request, "dashboard.html", days=days,
            kpis=analytics.kpis(conn, days), series=analytics.daily_series(conn, days),
            channels=rows, by_niche=analytics.views_by_niche(conn, days),
            alerts=analytics.alerts(conn), low_queue=analytics.low_queue(rows),
            quota=analytics.quota_today(conn), upcoming=_upcoming(conn, hours=48, limit=8),
        )


@app.get("/channels/{channel_id}")
def channel_page(request: Request, channel_id: int, days: int = 28, notice: str = "", problem: str = ""):
    days = days_param(days)
    with db.session() as conn:
        channel = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if not channel:
            return Response("Channel not found", status_code=404)
        now = timeutil.fmt(timeutil.now_local())
        queue_rows = conn.execute(
            "SELECT v.*, a.title audio_title, u.filename source FROM videos v LEFT JOIN audio a ON a.id = v.audio_id LEFT JOIN uploads u ON u.id = v.upload_id "
            "WHERE v.channel_id = ? AND (v.status != 'published' OR v.publish_at > ?) ORDER BY v.publish_at", (channel_id, now)).fetchall()
        return page(
            request, "channel.html", days=days, channel=dict(channel),
            kpis=analytics.kpis(conn, days, channel_id),
            series=analytics.daily_series(conn, days, channel_id),
            subs_series=analytics.daily_series(conn, days, channel_id, "net_subs"),
            top=analytics.top_videos(conn, days, channel_id, 8),
            heatmap=analytics.timing_heatmap(conn, 90, channel_id),
            queue=[dict(r) for r in queue_rows], slots=queue.slots(conn, channel_id),
            can_render=queue.can_render(channel["niche"]),
            notice=notice, problem=problem, client_ready=os.path.exists(youtube_sync.client_path()),
        )


@app.get("/schedule")
def schedule_page(request: Request, channel: int = 0):
    with db.session() as conn:
        items = _upcoming(conn, hours=24 * 14, channel_id=channel or None)
        groups = {}
        for item in items:
            groups.setdefault(item["publish_at"][:10], []).append(item)
        return page(
            request, "schedule.html", groups=groups, channel_filter=channel,
            channels=[dict(r) for r in conn.execute("SELECT id, name FROM channels ORDER BY name")],
            quota=analytics.quota_today(conn),
        )


@app.get("/content")
def content_page(request: Request, niche: str = "", problem: str = ""):
    with db.session() as conn:
        return page(request, "content.html", **_content_ctx(conn, niche), gen_problem=problem)


@app.post("/content/{niche}/generate")
def content_generate(niche: str, channel_id: int = Form(...), topic: str = Form(""), count: int = Form(3), instructions: str = Form("")):
    try:
        with db.session() as conn:
            draft_id = ai_drafts.start_draft(conn, niche, channel_id, topic, count, instructions)
        return RedirectResponse(f"/drafts/{draft_id}", status_code=303)
    except ActionError as e:
        return RedirectResponse(f"/content?niche={niche}&problem={_q(e)}#generate", status_code=303)


@app.get("/drafts/{draft_id}")
def draft_page(request: Request, draft_id: int, problem: str = ""):
    with db.session() as conn:
        try:
            draft = ai_drafts.load(conn, draft_id)
        except ActionError:
            return Response("Draft not found", status_code=404)
        return page(request, "draft.html", draft=draft, spec=NICHES[draft["niche"]], problem=problem, active_override="content")


@app.get("/api/drafts/{draft_id}")
def draft_status(draft_id: int):
    with db.session() as conn:
        row = conn.execute("SELECT status, error FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    return dict(row) if row else error("Draft not found.", 404)


@app.post("/drafts/{draft_id}/queue")
def draft_queue(draft_id: int):
    try:
        with db.session() as conn:
            added = ai_drafts.add_to_queue(conn, draft_id)
            channel_id = conn.execute("SELECT channel_id FROM drafts WHERE id = ?", (draft_id,)).fetchone()[0]
        return RedirectResponse(f"/channels/{channel_id}?notice=Added+{added}+videos+from+Gemini+to+the+queue.#queue", status_code=303)
    except ActionError as e:
        return RedirectResponse(f"/drafts/{draft_id}?problem={_q(e)}", status_code=303)


@app.get("/drafts/{draft_id}/excel")
def draft_excel(draft_id: int):
    with db.session() as conn:
        niche = conn.execute("SELECT niche FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if not niche:
            return Response("Draft not found", status_code=404)
        data = ai_drafts.excel(conn, draft_id)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="gemini_draft_{draft_id}_{niche[0]}.xlsx"'})


@app.post("/drafts/{draft_id}/discard")
def draft_discard(draft_id: int):
    with db.session() as conn:
        row = conn.execute("SELECT niche FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        ai_drafts.discard(conn, draft_id)
    return RedirectResponse(f"/content?niche={row[0] if row else ''}", status_code=303)


@app.post("/content/{niche}/upload")
async def content_upload(request: Request, niche: str, channel_id: int = Form(...), file: UploadFile = File(...)):
    if niche not in NICHES:
        return Response("Unknown niche", status_code=404)
    data = await file.read(MAX_SHEET_BYTES + 1)
    with db.session() as conn:
        ctx = _content_ctx(conn, niche)
        if len(data) > MAX_SHEET_BYTES:
            ctx["upload_error"] = "That file is over 10 MB; a content sheet should be far smaller."
        else:
            try:
                result, upload_id = queue.import_content(conn, niche, channel_id, file.filename or "upload.xlsx", data)
                ctx["result"] = {"ok": upload_id is not None, "errors": result.errors, "videos": len(result.videos), "filename": file.filename, "channel_id": channel_id}
                ctx.update({k: v for k, v in _content_ctx(conn, niche).items() if k in ("uploads", "ready")})
            except ActionError as e:
                ctx["upload_error"] = str(e)
        return page(request, "content.html", **ctx)


@app.get("/content/{niche}/template.xlsx")
def content_template(niche: str):
    if niche not in NICHES:
        return Response("Unknown niche", status_code=404)
    return Response(
        workbook_bytes(NICHES[niche]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{niche}_content_template.xlsx"'},
    )


@app.get("/audio")
def audio_page(request: Request, niche: str = ""):
    with db.session() as conn:
        return page(request, "audio.html", **_audio_ctx(conn, niche))


@app.post("/audio/{niche}")
async def audio_upload(request: Request, niche: str, files: List[UploadFile] = File(...), licence: str = Form("")):
    if niche not in NICHES:
        return Response("Unknown niche", status_code=404)
    added, problems = 0, []
    with db.session() as conn:
        for f in files:
            data = await f.read(MAX_AUDIO_BYTES + 1)
            if len(data) > MAX_AUDIO_BYTES:
                problems.append(f"{f.filename}: over 60 MB")
                continue
            try:
                queue.add_audio(conn, niche, f.filename or "track", data, licence)
                added += 1
            except ActionError as e:
                problems.append(str(e))
        ctx = _audio_ctx(conn, niche)
        ctx["notice"] = {"added": added, "problems": problems}
        return page(request, "audio.html", **ctx)


@app.get("/analytics")
def analytics_page(request: Request, days: int = 28):
    days = days_param(days)
    with db.session() as conn:
        return page(
            request, "analytics.html", days=days,
            kpis=analytics.kpis(conn, days),
            views=analytics.daily_series(conn, days),
            watch=analytics.daily_series(conn, days, metric="watch_hours"),
            subs=analytics.daily_series(conn, days, metric="net_subs"),
            by_niche=analytics.views_by_niche(conn, days),
            channels=analytics.channel_rows(conn, days),
            top=analytics.top_videos(conn, days, limit=15),
            heatmap=analytics.timing_heatmap(conn, days),
        )


# ---------- media ----------

@app.get("/media/audio/{audio_id}")
def audio_file(audio_id: int):
    with db.session() as conn:
        row = conn.execute("SELECT * FROM audio WHERE id = ?", (audio_id,)).fetchone()
    if not row or not os.path.exists(queue.audio_path(row)):
        return Response(status_code=404)
    return FileResponse(queue.audio_path(row))


@app.get("/media")
def media_page(request: Request, niche: str = "", status: str = ""):
    with db.session() as conn:
        return page(request, "media.html", **_media_ctx(conn, niche, status))


@app.get("/media/video/{video_id}")
def video_file(video_id: int, download: int = 0):
    with db.session() as conn:
        row = conn.execute("SELECT video_path, title FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row or not row["video_path"] or not os.path.exists(row["video_path"]):
        return Response(status_code=404)
    if download:
        name = re.sub(r"[^\w\- ]+", "", row["title"]).strip()[:80] or f"video-{video_id}"
        return FileResponse(row["video_path"], media_type="video/mp4", filename=f"{name}.mp4")
    return FileResponse(row["video_path"], media_type="video/mp4")


# ---------- JSON actions ----------

@app.get("/api/videos/{video_id}")
def video_status(video_id: int):
    with db.session() as conn:
        row = conn.execute("SELECT id, status, error, publish_at, video_path, upload_progress, youtube_video_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        return error("Video not found.", 404)
    return {**dict(row), "has_file": bool(row["video_path"])}


@app.post("/api/videos/{video_id}/schedule")
async def api_reschedule(video_id: int, request: Request):
    body = await request.json()
    try:
        with db.session() as conn:
            value = youtube_sync.reschedule(conn, video_id, str(body.get("publish_at", "")))
        return {"publish_at": value, "label": when(value)}
    except ActionError as e:
        return error(e)


@app.post("/api/videos/{video_id}/render")
def api_render(video_id: int):
    try:
        with db.session() as conn:
            queue.start_render(conn, video_id)
        return {"status": "rendering"}
    except ActionError as e:
        return error(e)


@app.post("/api/videos/{video_id}/youtube")
def api_youtube(video_id: int):
    try:
        with db.session() as conn:
            youtube_sync.start_upload(conn, video_id)
            status = conn.execute("SELECT status FROM videos WHERE id = ?", (video_id,)).fetchone()[0]
        return {"status": status}
    except ActionError as e:
        return error(e)


@app.post("/api/videos/{video_id}/delete")
def api_delete_video(video_id: int):
    try:
        with db.session() as conn:
            queue.delete_video(conn, video_id)
        return {"deleted": True}
    except ActionError as e:
        return error(e)


@app.post("/api/channels/{channel_id}/slots")
async def api_slots(channel_id: int, request: Request):
    body = await request.json()
    try:
        with db.session() as conn:
            return {"slots": queue.set_slots(conn, channel_id, list(body.get("slots", [])))}
    except ActionError as e:
        return error(e)


@app.post("/api/audio/{audio_id}/delete")
def api_delete_audio(audio_id: int):
    try:
        with db.session() as conn:
            queue.delete_audio(conn, audio_id)
        return {"deleted": True}
    except ActionError as e:
        return error(e)


# ---------- settings and YouTube connection ----------

@app.get("/settings")
def settings_page(request: Request, notice: str = "", problem: str = ""):
    with db.session() as conn:
        return page(request, "settings.html", **_settings_ctx(conn, request), notice=notice, problem=problem)


@app.post("/settings/client")
async def settings_client(request: Request, file: UploadFile = File(...)):
    try:
        youtube_sync.save_client_file(await file.read(64 * 1024))
        return RedirectResponse("/settings?notice=OAuth+client+saved.", status_code=303)
    except ActionError as e:
        return RedirectResponse(f"/settings?problem={_q(e)}", status_code=303)


@app.post("/settings/channels")
def settings_add_channel(name: str = Form(""), niche: str = Form(""), slots: str = Form("")):
    try:
        with db.session() as conn:
            channel_id = youtube_sync.add_channel(conn, name, niche, slots)
        return RedirectResponse(f"/channels/{channel_id}", status_code=303)
    except ActionError as e:
        return RedirectResponse(f"/settings?problem={_q(e)}", status_code=303)


@app.post("/settings/connect")
def settings_connect(request: Request, niche: str = Form(""), slots: str = Form("")):
    try:
        url = youtube_sync.start_new_connect(niche, slots, str(request.base_url))
        return RedirectResponse(url, status_code=303)
    except (ActionError, YouTubeError) as e:
        return RedirectResponse(f"/settings?problem={_q(e)}#channels", status_code=303)


@app.post("/settings/gemini")
def settings_gemini(api_key: str = Form("")):
    try:
        with db.session() as conn:
            found = ai_drafts.save_key(conn, api_key)
        return RedirectResponse(f"/settings?notice=Gemini+key+works%3B+{len(found)}+models+available.#gemini", status_code=303)
    except ActionError as e:
        return RedirectResponse(f"/settings?problem={_q(e)}#gemini", status_code=303)


@app.post("/settings/gemini/model")
def settings_gemini_model(model: str = Form("")):
    try:
        with db.session() as conn:
            ai_drafts.set_model(conn, model)
        return RedirectResponse("/settings?notice=Gemini+model+saved.#gemini", status_code=303)
    except ActionError as e:
        return RedirectResponse(f"/settings?problem={_q(e)}#gemini", status_code=303)


@app.post("/settings/gemini/remove")
def settings_gemini_remove():
    with db.session() as conn:
        ai_drafts.remove_key(conn)
    return RedirectResponse("/settings?notice=Gemini+key+removed.#gemini", status_code=303)


@app.post("/settings/remove-mock")
def settings_remove_mock():
    with db.session() as conn:
        removed = youtube_sync.remove_mock_data(conn)
    return RedirectResponse(f"/settings?notice=Removed+{removed}+mock+channels+and+their+data.", status_code=303)


@app.get("/oauth/start")
def oauth_start(request: Request, channel: int):
    try:
        with db.session() as conn:
            url = youtube_sync.start_connect(conn, channel, str(request.base_url))
        return RedirectResponse(url, status_code=303)
    except (ActionError, YouTubeError) as e:
        return RedirectResponse(f"/channels/{channel}?problem={_q(e)}", status_code=303)


@app.get("/oauth/callback")
def oauth_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    pending = youtube_sync._pending.get(state, {})
    back = f"/channels/{pending['channel_id']}" if pending.get("channel_id") else "/settings"
    if error:
        youtube_sync._pending.pop(state, None)
        message = "You cancelled the sign-in." if error == "access_denied" else f"Google returned: {error}"
        return RedirectResponse(f"{back}?problem={_q(message)}", status_code=303)
    try:
        with db.session() as conn:
            channel_id = youtube_sync.finish_connect(conn, state, code, str(request.base_url))
        return RedirectResponse(f"/channels/{channel_id}?notice=Connected+to+YouTube.", status_code=303)
    except (ActionError, YouTubeError) as e:
        return RedirectResponse(f"{back}?problem={_q(e)}", status_code=303)


@app.post("/api/channels/{channel_id}/sync")
def api_sync(channel_id: int):
    try:
        with db.session() as conn:
            result = youtube_sync.sync_channel(conn, channel_id)
        return {"synced": True, **result}
    except ActionError as e:
        return error(e)


@app.post("/api/channels/{channel_id}/disconnect")
def api_disconnect(channel_id: int):
    with db.session() as conn:
        youtube_sync.disconnect(conn, channel_id)
    return {"disconnected": True}


def _q(message) -> str:
    from urllib.parse import quote_plus

    return quote_plus(str(message)[:300])


def _settings_ctx(conn, request: Request):
    return {
        "client": youtube_sync.client_status(str(request.base_url)),
        "gemini": ai_drafts.status(conn),
        "channels": [dict(r) for r in conn.execute("SELECT id, name, niche, connection, is_mock, youtube_channel_id, last_synced_at FROM channels ORDER BY is_mock, name")],
        "mock_count": conn.execute("SELECT COUNT(*) FROM channels WHERE is_mock = 1").fetchone()[0],
        "niche_options": [(k, s.name) for k, s in NICHES.items()],
    }


# ---------- shared queries ----------

def _upcoming(conn, hours: int, limit: int = 500, channel_id: int = None):
    now = timeutil.now_local()
    end = now + dt.timedelta(hours=hours)
    where = "v.status IN ('ready','rendering','rendered','scheduled','failed') AND v.publish_at > ? AND v.publish_at <= ?"
    args = [timeutil.fmt(now), timeutil.fmt(end)]
    if channel_id:
        where += " AND v.channel_id = ?"
        args.append(channel_id)
    rows = conn.execute(
        f"SELECT v.id, v.title, v.status, v.publish_at, v.error, v.channel_id, v.content_json, v.is_mock, v.youtube_video_id, c.name channel_name, c.niche, u.filename source "
        f"FROM videos v JOIN channels c ON c.id = v.channel_id LEFT JOIN uploads u ON u.id = v.upload_id WHERE {where} ORDER BY v.publish_at LIMIT ?", args + [limit]).fetchall()
    return [dict(r) for r in rows]


def _content_ctx(conn, niche: str):
    niche = niche if niche in NICHES else next(iter(NICHES))
    spec = NICHES[niche]
    channels = [dict(r) for r in conn.execute("SELECT id, name, connection FROM channels WHERE niche = ? ORDER BY name", (niche,))]
    counts = {r["niche"]: r["n"] for r in conn.execute(
        "SELECT c.niche, COUNT(*) n FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.status IN ('ready','rendered') GROUP BY c.niche")}
    uploads = [dict(r) for r in conn.execute(
        "SELECT u.*, c.name channel_name FROM uploads u LEFT JOIN channels c ON c.id = u.channel_id WHERE u.niche = ? ORDER BY u.id DESC LIMIT 20", (niche,))]
    ready = [dict(r) for r in conn.execute(
        "SELECT v.id, v.title, v.status, v.publish_at, v.error, v.channel_id, v.content_json, v.is_mock, v.youtube_video_id, c.name channel_name, u.filename source "
        "FROM videos v JOIN channels c ON c.id = v.channel_id LEFT JOIN uploads u ON u.id = v.upload_id "
        "WHERE c.niche = ? AND v.status IN ('ready','rendering','rendered','failed') AND v.is_mock = 0 ORDER BY v.publish_at", (niche,))]
    return {
        "niches": [{"id": k, "name": s.name, "aspect": s.aspect_ratio, "pending": counts.get(k, 0), "renders": queue.can_render(k)} for k, s in NICHES.items()],
        "niche": niche, "spec": spec, "channels": channels, "uploads": uploads, "ready": ready,
        "can_render": queue.can_render(niche),
        "gemini": ai_drafts.status(conn), "drafts": ai_drafts.recent(conn, niche),
        "items_text": f"{spec.items.min_count}–{spec.items.max_count} {spec.items.label}s" if spec.items.min_count != spec.items.max_count else f"{spec.items.min_count} {spec.items.label}s",
    }


MEDIA_FILTERS = {"rendered": ("rendered",), "youtube": ("uploading", "scheduled", "published")}


def _media_ctx(conn, niche: str, status: str):
    """Every rendered video file on this PC, newest first, with its size and shape."""
    rows = conn.execute(
        "SELECT v.id, v.title, v.status, v.publish_at, v.duration_s, v.video_path, v.youtube_video_id, v.channel_id, "
        "c.name channel_name, c.niche, a.title audio_title FROM videos v JOIN channels c ON c.id = v.channel_id "
        "LEFT JOIN audio a ON a.id = v.audio_id WHERE v.is_mock = 0 AND v.video_path IS NOT NULL ORDER BY v.id DESC").fetchall()
    videos = []
    for r in rows:
        v = dict(r)
        if not os.path.exists(v["video_path"]):
            continue
        stat = os.stat(v["video_path"])
        v["size"] = stat.st_size
        v["rendered_at"] = timeutil.fmt(dt.datetime.fromtimestamp(stat.st_mtime))
        v["aspect"] = NICHES[v["niche"]].aspect_ratio if v["niche"] in NICHES else "9:16"
        videos.append(v)
    counts = {}
    for v in videos:
        counts[v["niche"]] = counts.get(v["niche"], 0) + 1
    niche = niche if niche in NICHES else ""
    status = status if status in MEDIA_FILTERS else ""
    shown = [v for v in videos if (not niche or v["niche"] == niche) and (not status or v["status"] in MEDIA_FILTERS[status])]
    return {
        "niches": [{"id": k, "name": s.name, "count": counts.get(k, 0)} for k, s in NICHES.items()],
        "niche": niche, "status": status, "all_count": len(videos),
        "videos": shown, "shown_seconds": sum(v["duration_s"] or 0 for v in shown), "shown_bytes": sum(v["size"] for v in shown),
    }


def _audio_ctx(conn, niche: str):
    niche = niche if niche in NICHES else next(iter(NICHES))
    counts = {r["niche"]: r["n"] for r in conn.execute("SELECT niche, COUNT(*) n FROM audio GROUP BY niche")}
    tracks = [dict(r) for r in conn.execute("SELECT * FROM audio WHERE niche = ? ORDER BY uploaded_at DESC", (niche,))]
    return {
        "niches": [{"id": k, "name": s.name, "tracks": counts.get(k, 0)} for k, s in NICHES.items()],
        "niche": niche, "niche_label": NICHES[niche].name, "tracks": tracks,
    }
