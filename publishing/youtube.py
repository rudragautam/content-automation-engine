"""YouTube Data API v3 and YouTube Analytics API v2.

Covers what the hub needs: one OAuth sign-in per channel, uploading a video
as private with a scheduled publish time, and reading channel stats.
Functions take already-built API service objects so they can be tested
with fakes; build_services() makes the real ones.

Every upload costs about 1,600 quota units out of a default 10,000 a day
per Google Cloud project. Until the project passes YouTube's API audit,
YouTube keeps API uploads private and ignores publishAt.
"""

import datetime as dt
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SCOPES = [
    # Upload, read the channel, and change a scheduled video's publish time (videos.update).
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
UPLOAD_COST = 1600
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
TAGS_LIMIT = 500
CHUNK_BYTES = 8 * 1024 * 1024


class YouTubeError(Exception):
    """A YouTube problem with a message fit to show the user."""


class NotAuthorized(YouTubeError):
    """The channel's sign-in is missing, expired or revoked; it must be reconnected."""


class QuotaExceeded(YouTubeError):
    """The project's daily API quota is used up."""


# ---------- OAuth ----------

def read_client_config(path: str) -> Dict[str, Any]:
    """The OAuth client file downloaded from Google Cloud ("web" or "installed" type)."""
    with open(path, encoding="utf-8") as f:
        return parse_client_config(f.read())


def parse_client_config(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except ValueError:
        raise YouTubeError("That file isn't JSON. Download the OAuth client file from Google Cloud → Credentials.")
    kind = next((k for k in ("web", "installed") if k in data), None)
    if not kind or not data[kind].get("client_id") or not data[kind].get("client_secret"):
        raise YouTubeError("That JSON isn't an OAuth client file; it needs a client_id and client_secret.")
    return {"kind": kind, "client_id": data[kind]["client_id"], "redirect_uris": data[kind].get("redirect_uris", []), "raw": data}


def authorization_url(client_path: str, redirect_uri: str, state: str) -> Tuple[str, str]:
    """URL of Google's consent screen, and the PKCE verifier needed to finish the sign-in."""
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(client_path, scopes=SCOPES, redirect_uri=redirect_uri, state=state, autogenerate_code_verifier=True)
    # offline + consent so Google always returns a refresh token for unattended uploads.
    url, _ = flow.authorization_url(access_type="offline", prompt="consent select_account", include_granted_scopes="true")
    return url, flow.code_verifier


def exchange_code(client_path: str, redirect_uri: str, state: str, code: str, code_verifier: str):
    from google_auth_oauthlib.flow import Flow

    # Partial grants are checked below with a clear message instead of oauthlib's bare Warning.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = Flow.from_client_secrets_file(client_path, scopes=SCOPES, redirect_uri=redirect_uri, state=state)
    flow.code_verifier = code_verifier
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise YouTubeError(f"Google refused the sign-in: {e}")
    creds = flow.credentials
    if not creds.refresh_token:
        raise YouTubeError("Google didn't return a refresh token. Remove the app's access at myaccount.google.com/permissions and connect again.")
    granted = flow.oauth2session.token.get("scope") or SCOPES
    granted = set(granted.split() if isinstance(granted, str) else granted)
    missing = set(SCOPES) - granted
    if missing:
        raise YouTubeError("Some permissions were left unticked on Google's screen. Connect again and allow all of them.")
    return creds


def save_credentials(creds, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def load_credentials(path: str):
    """Stored credentials, refreshed if needed. Raises NotAuthorized if they no longer work."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not os.path.exists(path):
        raise NotAuthorized("This channel isn't connected to YouTube.")
    creds = Credentials.from_authorized_user_file(path, SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError:
            raise NotAuthorized("YouTube sign-in expired or was revoked. Reconnect the channel.")
        save_credentials(creds, path)
    return creds


def build_services(creds):
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    return youtube, analytics


# ---------- channel ----------

def my_channel(youtube) -> Dict[str, Any]:
    """The channel the credentials belong to."""
    res = _call(youtube.channels().list(part="id,snippet,statistics,contentDetails", mine=True))
    items = res.get("items") or []
    if not items:
        raise YouTubeError("This Google account has no YouTube channel. Pick the channel's account on Google's screen.")
    ch = items[0]
    return {
        "id": ch["id"],
        "title": ch["snippet"]["title"],
        "handle": ch["snippet"].get("customUrl", ""),
        "subscribers": int(ch.get("statistics", {}).get("subscriberCount", 0) or 0),
        "uploads_playlist": ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
    }


# ---------- upload ----------

def to_utc_rfc3339(local: str, timezone: str) -> str:
    """'2026-10-25T19:00' in the channel's timezone -> '2026-10-25T13:30:00Z'."""
    when = dt.datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(timezone))
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(text: str) -> str:
    # YouTube rejects < and > in titles and descriptions.
    return (text or "").replace("<", "‹").replace(">", "›").strip()


def upload_body(
    title: str,
    description: str,
    tags: List[str],
    publish_at_utc: Optional[str],
    category_id: str = "27",
    language: str = "en",
    made_for_kids: bool = False,
    synthetic_media: bool = True,
) -> Dict[str, Any]:
    title = _clean(title)
    if not title:
        raise YouTubeError("The video needs a title.")
    kept, total = [], 0
    for tag in (re.sub(r"[<>]", "", t).strip() for t in tags):
        cost = len(tag) + (2 if " " in tag else 0) + (1 if kept else 0)  # YouTube counts quotes and commas
        if tag and total + cost <= TAGS_LIMIT:
            kept.append(tag)
            total += cost
    status = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": made_for_kids,
        # AI-written, template-rendered videos count as altered or synthetic content.
        "containsSyntheticMedia": synthetic_media,
    }
    if publish_at_utc:
        status["publishAt"] = publish_at_utc
    return {
        "snippet": {
            "title": title[:TITLE_LIMIT],
            "description": _clean(description)[:DESCRIPTION_LIMIT],
            "tags": kept,
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": status,
    }


def upload_video(youtube, path: str, body: Dict[str, Any], progress: Callable[[float], None] = None) -> str:
    """Resumable upload; returns the new video's ID."""
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(path, mimetype="video/mp4", chunksize=CHUNK_BYTES, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = _call(request, next_chunk=True)
        if status and progress:
            progress(status.progress())
    if "id" not in response:
        raise YouTubeError(f"YouTube didn't return a video ID: {response}")
    return response["id"]


def set_publish_time(youtube, video_id: str, publish_at_utc: str) -> None:
    """Move a scheduled (private) video's public release time."""
    items = _call(youtube.videos().list(part="status", id=video_id)).get("items") or []
    if not items:
        raise YouTubeError("YouTube no longer has this video; it may have been deleted in Studio.")
    status = items[0]["status"]
    if status.get("privacyStatus") != "private":
        raise YouTubeError("This video is already public on YouTube, so its release time can't change.")
    status["publishAt"] = publish_at_utc
    _call(youtube.videos().update(part="status", body={"id": video_id, "status": status}))


# ---------- stats ----------

def daily_stats(analytics, start: dt.date, end: dt.date) -> List[Dict[str, Any]]:
    res = _call(analytics.reports().query(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost", dimensions="day", sort="day"))
    return [
        {"date": r[0], "views": int(r[1]), "watch_minutes": int(r[2]), "subs_gained": int(r[3]), "subs_lost": int(r[4])}
        for r in res.get("rows") or []
    ]


def recent_videos(youtube, uploads_playlist: str, limit: int = 50) -> List[Dict[str, Any]]:
    items = _call(youtube.playlistItems().list(part="contentDetails", playlistId=uploads_playlist, maxResults=min(limit, 50))).get("items") or []
    ids = [i["contentDetails"]["videoId"] for i in items]
    if not ids:
        return []
    res = _call(youtube.videos().list(part="snippet,statistics,status,contentDetails", id=",".join(ids)))
    out = []
    for v in res.get("items") or []:
        stats = v.get("statistics", {})
        out.append({
            "id": v["id"],
            "title": v["snippet"]["title"],
            "published_at": v["snippet"].get("publishedAt"),
            "privacy": v["status"].get("privacyStatus"),
            "publish_at": v["status"].get("publishAt"),
            "duration_s": _iso_duration(v.get("contentDetails", {}).get("duration", "")),
            "views": int(stats.get("viewCount", 0) or 0),
            "likes": int(stats.get("likeCount", 0) or 0),
            "comments": int(stats.get("commentCount", 0) or 0),
        })
    return out


def _iso_duration(value: str) -> Optional[float]:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return float(h * 3600 + mi * 60 + s)


# ---------- errors ----------

def _call(request, next_chunk: bool = False):
    """Execute a request, turning Google's errors into ones the hub can act on."""
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    try:
        return request.next_chunk() if next_chunk else request.execute()
    except RefreshError:
        raise NotAuthorized("YouTube sign-in expired or was revoked. Reconnect the channel.")
    except HttpError as e:
        raise _translate(e)


def _translate(error) -> YouTubeError:
    status = getattr(error.resp, "status", 0)
    try:
        detail = json.loads(error.content.decode("utf-8"))["error"]
        reason = (detail.get("errors") or [{}])[0].get("reason", "")
        message = detail.get("message", "")
    except Exception:
        reason, message = "", str(error)
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
        return QuotaExceeded("The YouTube API daily quota is used up. Uploads resume after it resets at midnight Pacific time.")
    if reason == "uploadLimitExceeded":
        return YouTubeError("YouTube's daily upload limit for this channel is reached. Try again tomorrow.")
    if status == 401:
        return NotAuthorized("YouTube sign-in expired or was revoked. Reconnect the channel.")
    if status == 403 and reason in ("forbidden", "insufficientPermissions"):
        return NotAuthorized("The channel's sign-in lacks a permission. Reconnect it and allow everything on Google's screen.")
    return YouTubeError(f"YouTube error {status}: {message or reason}")
