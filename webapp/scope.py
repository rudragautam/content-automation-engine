"""The global channel filter shown at the top right of the overview pages.

Two choices narrow every number and list on those pages:
    created  all | live (the channel exists on YouTube) | planned (added in the hub, not created on YouTube yet)
    channel  one channel, or every channel that matches `created`
The choice comes from the query string and is remembered in cookies, so it
follows the user from page to page until it is changed.
"""

from typing import Any, Dict, List, Mapping, Optional

CREATED = {"all": "All channels", "live": "Created on YouTube", "planned": "Not created yet"}
COOKIE_CHANNEL, COOKIE_CREATED = "hub_channel", "hub_created"


def is_live(channel: Mapping[str, Any]) -> bool:
    return bool(channel["youtube_channel_id"])


def resolve(conn, query: Mapping[str, str], cookies: Mapping[str, str]) -> Dict[str, Any]:
    created = query.get("created", cookies.get(COOKIE_CREATED, "all"))
    created = created if created in CREATED else "all"
    raw = query.get("ch", cookies.get(COOKIE_CHANNEL, ""))
    channels = [dict(r) for r in conn.execute("SELECT id, name, connection, youtube_channel_id FROM channels ORDER BY name COLLATE NOCASE")]
    live = [c for c in channels if is_live(c)]
    planned = [c for c in channels if not is_live(c)]
    options = {"all": channels, "live": live, "planned": planned}[created]
    channel = next((c for c in options if str(c["id"]) == str(raw)), None)

    ids: Optional[List[int]]
    if channel:
        ids = [channel["id"]]
    elif created == "all":
        ids = None  # no filter at all
    else:
        ids = [c["id"] for c in options]
    return {
        "created": created, "channel": channel, "ids": ids,
        "live": live, "planned": planned, "total": len(channels),
        "label": channel["name"] if channel else CREATED[created],
        "active": bool(channel) or created != "all",
    }


def keep(scope: Dict[str, Any], response) -> None:
    """Remember the choice for the next page."""
    for key, value in ((COOKIE_CREATED, scope["created"]), (COOKIE_CHANNEL, str(scope["channel"]["id"]) if scope["channel"] else "")):
        response.set_cookie(key, value, max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True)


def includes(scope: Dict[str, Any], channel_id: int) -> bool:
    return scope["ids"] is None or channel_id in scope["ids"]
