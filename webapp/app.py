"""Content hub web app: dashboard, channels, schedule, content, audio, analytics."""

import datetime as dt
import json
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from content_templates import NICHES, workbook_bytes
from webapp import analytics, db, mock, queue, timeutil
from webapp.queue import ActionError

HERE = os.path.dirname(os.path.abspath(__file__))
RANGES = (7, 28, 90)
MAX_SHEET_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 60 * 1024 * 1024

@asynccontextmanager
async def lifespan(_app):
    db.init()
    with db.session() as conn:
        mock.seed(conn)
        # A render interrupted by a restart would otherwise stay "rendering" forever.
        conn.execute("UPDATE videos SET status = 'failed', error = 'Render interrupted by a restart; render again.' WHERE status = 'rendering'")
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
    return templates.TemplateResponse(request, name, {"active": name.split(".")[0], "ranges": RANGES, **ctx})


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
def channel_page(request: Request, channel_id: int, days: int = 28):
    days = days_param(days)
    with db.session() as conn:
        channel = conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()
        if not channel:
            return Response("Channel not found", status_code=404)
        now = timeutil.fmt(timeutil.now_local())
        queue_rows = conn.execute(
            "SELECT v.*, a.title audio_title FROM videos v LEFT JOIN audio a ON a.id = v.audio_id "
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
def content_page(request: Request, niche: str = ""):
    with db.session() as conn:
        return page(request, "content.html", **_content_ctx(conn, niche))


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


@app.get("/media/video/{video_id}")
def video_file(video_id: int):
    with db.session() as conn:
        row = conn.execute("SELECT video_path FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row or not row["video_path"] or not os.path.exists(row["video_path"]):
        return Response(status_code=404)
    return FileResponse(row["video_path"], media_type="video/mp4")


# ---------- JSON actions ----------

@app.get("/api/videos/{video_id}")
def video_status(video_id: int):
    with db.session() as conn:
        row = conn.execute("SELECT id, status, error, publish_at, video_path FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        return error("Video not found.", 404)
    return {**dict(row), "has_file": bool(row["video_path"])}


@app.post("/api/videos/{video_id}/schedule")
async def api_reschedule(video_id: int, request: Request):
    body = await request.json()
    try:
        with db.session() as conn:
            value = queue.reschedule(conn, video_id, str(body.get("publish_at", "")))
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
            queue.schedule_on_youtube(conn, video_id)
        return {"status": "scheduled"}
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
        f"SELECT v.id, v.title, v.status, v.publish_at, v.error, v.channel_id, v.content_json, v.is_mock, c.name channel_name, c.niche "
        f"FROM videos v JOIN channels c ON c.id = v.channel_id WHERE {where} ORDER BY v.publish_at LIMIT ?", args + [limit]).fetchall()
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
        "SELECT v.id, v.title, v.status, v.publish_at, v.error, v.channel_id, v.content_json, v.is_mock, c.name channel_name FROM videos v JOIN channels c ON c.id = v.channel_id "
        "WHERE c.niche = ? AND v.status IN ('ready','rendering','rendered','failed') AND v.is_mock = 0 ORDER BY v.publish_at", (niche,))]
    return {
        "niches": [{"id": k, "name": s.name, "aspect": s.aspect_ratio, "pending": counts.get(k, 0), "renders": queue.can_render(k)} for k, s in NICHES.items()],
        "niche": niche, "spec": spec, "channels": channels, "uploads": uploads, "ready": ready,
        "can_render": queue.can_render(niche),
        "items_text": f"{spec.items.min_count}–{spec.items.max_count} {spec.items.label}s" if spec.items.min_count != spec.items.max_count else f"{spec.items.min_count} {spec.items.label}s",
    }


def _audio_ctx(conn, niche: str):
    niche = niche if niche in NICHES else next(iter(NICHES))
    counts = {r["niche"]: r["n"] for r in conn.execute("SELECT niche, COUNT(*) n FROM audio GROUP BY niche")}
    tracks = [dict(r) for r in conn.execute("SELECT * FROM audio WHERE niche = ? ORDER BY uploaded_at DESC", (niche,))]
    return {
        "niches": [{"id": k, "name": s.name, "tracks": counts.get(k, 0)} for k, s in NICHES.items()],
        "niche": niche, "niche_label": NICHES[niche].name, "tracks": tracks,
    }
