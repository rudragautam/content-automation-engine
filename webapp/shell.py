"""What the app shell shows on every page: the Channels menu, the active channel, its palette,
and where each menu entry and navigation item leads.

The active channel is the one the page is about (a channel, its analysis, a draft or video of
it); otherwise the one picked in the Channels menu, remembered in the same cookie as the
overview pages' channel filter (webapp.scope). Picking a channel adds ?ch=<id> to the page,
so overview pages filter to it and every page after that wears its palette.
"""

from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlencode

from webapp import scope, themes

# page name -> navigation section
SECTIONS = {
    "dashboard": "dashboard", "channel": "dashboard", "setup": "dashboard",
    "analytics": "analytics",
    "analysis": "optimizer", "compare": "optimizer", "optimizer": "optimizer",
    "content": "drafts", "draft": "drafts",
    "schedule": "schedule", "suggestions": "schedule",
    "media": "media", "audio": "audio", "settings": "settings",
}
# pages about one channel: switching channel opens the new channel's page instead
CHANNEL_PAGES = {"channel", "analysis", "compare", "setup"}


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_channel_id(ctx: Mapping[str, Any]) -> Optional[int]:
    for key in ("channel", "video", "draft"):
        item = ctx.get(key)
        if isinstance(item, Mapping):
            cid = item.get("id") if key == "channel" else item.get("channel_id")
            if cid:
                return int(cid)
    sc = ctx.get("scope")
    if isinstance(sc, Mapping) and sc.get("channel"):
        return int(sc["channel"]["id"])
    return None


def context(conn, request, page_name: str, ctx: Mapping[str, Any]) -> Dict[str, Any]:
    rows = [dict(r) for r in conn.execute(
        "SELECT c.id, c.name, c.handle, c.connection, c.youtube_channel_id, c.subscribers, c.is_mock, c.theme, "
        "(SELECT MAX(v.publish_at) FROM videos v WHERE v.channel_id = c.id AND v.status = 'published') last_upload "
        "FROM channels c ORDER BY c.is_mock, c.youtube_channel_id IS NULL, c.subscribers DESC, c.name COLLATE NOCASE")]
    real = [c for c in rows if not c["is_mock"]]
    shown = real or rows
    by_id = {c["id"]: c for c in rows}

    picked = request.query_params.get("ch")
    active_id = _page_channel_id(ctx)
    if active_id is None and picked is not None:
        active_id = _int(picked)
    if active_id is None and picked is None:
        active_id = _int(request.cookies.get(scope.COOKIE_CHANNEL))
    active = by_id.get(active_id)

    for c in rows:
        c["palette"] = themes.palette(c["theme"])
        c["colour"] = themes.avatar_colour(c["theme"])
        c["status"] = "ok" if c["connection"] == "connected" else "warn" if c["connection"] == "expired" else "off"
        c["switch_url"] = switch_url(request, page_name, ctx, c["id"])

    audit = None
    if active and active["youtube_channel_id"]:
        audit = conn.execute("SELECT id, status, score FROM channel_audits WHERE channel_id = ? ORDER BY id DESC LIMIT 1", (active["id"],)).fetchone()
    if active and audit:
        optimizer_href = f"/channels/{active['id']}/analysis/{audit['id']}"
    elif active:
        optimizer_href = f"/channels/{active['id']}#analysis"
    else:
        optimizer_href = "/#optimizer"

    return {
        "shell_channels": [c for c in shown if c["youtube_channel_id"]],
        "shell_planned": [c for c in shown if not c["youtube_channel_id"]],
        "active_channel": active,
        "palette": active["palette"] if active else themes.DEFAULT,
        "palettes": themes.PALETTES,
        "section": SECTIONS.get(page_name, page_name),
        "all_channels_url": switch_url(request, page_name, ctx, None),
        "optimizer_href": optimizer_href,
        "remember_channel": picked is not None and "scope" not in ctx,
        "picked_channel": active["id"] if active and picked is not None else None,
    }


def switch_url(request, page_name: str, ctx: Mapping[str, Any], channel_id: Optional[int]) -> str:
    """Where a Channels menu entry leads from this page (None = all channels)."""
    if page_name in CHANNEL_PAGES and channel_id is not None:
        return f"/channels/{channel_id}"
    if page_name in CHANNEL_PAGES or page_name in ("draft", "suggestions"):
        return "/?" + urlencode({"created": "all", "ch": "" if channel_id is None else str(channel_id)})
    params: List = [(k, v) for k, v in request.query_params.multi_items() if k not in ("ch", "created", "notice", "problem", "page", "qpage")]
    params += [("created", "all"), ("ch", "" if channel_id is None else str(channel_id))]
    return request.url.path + "?" + urlencode(params)


def remember(response, channel_id: Optional[int]) -> None:
    """A channel picked in the menu on a page without the channel filter: keep it for the next pages."""
    response.set_cookie(scope.COOKIE_CHANNEL, "" if channel_id is None else str(channel_id), max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True)
    response.set_cookie(scope.COOKIE_CREATED, "all", max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True)
