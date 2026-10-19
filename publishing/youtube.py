"""YouTube Data API v3 and YouTube Analytics API v2.

Covers what the hub needs: one OAuth sign-in per channel, uploading a video
as private with a scheduled publish time, and reading channel stats.
Functions take already-built API service objects so they can be tested
with fakes; build_services() makes the real ones.

Every upload costs about 1,600 quota units out of a default 10,000 a day
per Google Cloud project. Until the project passes YouTube's API audit,
YouTube keeps API uploads private and ignores publishAt.
"""

import base64
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
# Asked for at sign-in only, so the hub can show which Google account a channel uses.
# Stored sign-ins keep working with SCOPES alone.
LOGIN_SCOPES = SCOPES + ["openid", "https://www.googleapis.com/auth/userinfo.email"]
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

    flow = Flow.from_client_secrets_file(client_path, scopes=LOGIN_SCOPES, redirect_uri=redirect_uri, state=state, autogenerate_code_verifier=True)
    # offline + consent so Google always returns a refresh token for unattended uploads.
    url, _ = flow.authorization_url(access_type="offline", prompt="consent select_account", include_granted_scopes="true")
    return url, flow.code_verifier


def exchange_code(client_path: str, redirect_uri: str, state: str, code: str, code_verifier: str):
    from google_auth_oauthlib.flow import Flow

    # Partial grants are checked below with a clear message instead of oauthlib's bare Warning.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow = Flow.from_client_secrets_file(client_path, scopes=LOGIN_SCOPES, redirect_uri=redirect_uri, state=state)
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


def account_email(creds) -> str:
    """The Google account behind a fresh sign-in, from its ID token ('' if Google didn't send one).
    The token came straight from Google's token endpoint over TLS, so it is only decoded, not verified."""
    token = getattr(creds, "id_token", None)
    if not token or token.count(".") != 2:
        return ""
    payload = token.split(".")[1]
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return ""
    return str(data.get("email") or "")[:200]


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


HTTP_TIMEOUT = 300  # seconds; long enough for an 8 MB upload chunk on a slow line, short enough not to hang forever


def build_services(creds):
    import google_auth_httplib2
    import httplib2
    from googleapiclient.discovery import build

    def http():
        return google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=HTTP_TIMEOUT))

    youtube = build("youtube", "v3", http=http(), cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", http=http(), cache_discovery=False)
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


# ---------- channel setup ----------
# Name, @handle and profile picture can only be changed in YouTube Studio; everything
# below is what the Data API allows. Each write costs 50 quota units, each read 1.

ABOUT_LIMIT = 1000        # channel description
KEYWORDS_LIMIT = 500      # channel keywords, as YouTube stores them (space separated, quoted phrases)
WRITE_COST = 50


def format_keywords(words: List[str]) -> str:
    """['ai', 'deep learning'] -> 'ai "deep learning"' (YouTube's channel keyword format)."""
    out = []
    for w in (re.sub(r'["<>]', "", w).strip() for w in words):
        if w:
            out.append(f'"{w}"' if " " in w else w)
    return " ".join(out)


def parse_keywords(text: str) -> List[str]:
    return [a or b for a, b in re.findall(r'"([^"]+)"|(\S+)', text or "")]


def channel_setup(youtube) -> Dict[str, Any]:
    """Everything the setup window shows, read in one call."""
    res = _call(youtube.channels().list(part="snippet,brandingSettings,contentDetails,status", mine=True))
    items = res.get("items") or []
    if not items:
        raise YouTubeError("This sign-in has no YouTube channel.")
    ch = items[0]
    branding = ch.get("brandingSettings", {})
    info = branding.get("channel", {})
    thumbs = ch.get("snippet", {}).get("thumbnails", {})
    return {
        "id": ch["id"],
        "title": ch["snippet"]["title"],
        "handle": ch["snippet"].get("customUrl", ""),
        "thumbnail": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
        "description": info.get("description", ""),
        "keywords": parse_keywords(info.get("keywords", "")),
        "country": info.get("country", ""),
        "language": info.get("defaultLanguage", ""),
        "trailer": info.get("unsubscribedTrailer", ""),
        "banner": branding.get("image", {}).get("bannerExternalUrl", ""),
        "uploads_playlist": ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        "made_for_kids": ch.get("status", {}).get("madeForKids"),
        "branding": branding,
    }


def update_branding(youtube, channel_id: str, branding: Dict[str, Any], channel: Dict[str, Any] = None, image: Dict[str, Any] = None) -> None:
    """channels.update replaces the whole brandingSettings part, so start from what is
    there now and change only the given fields. The title is never sent: YouTube only
    lets Studio change it."""
    merged = json.loads(json.dumps(branding or {}))
    info = {k: v for k, v in merged.get("channel", {}).items() if k != "title"}
    info.update({k: v for k, v in (channel or {}).items() if v is not None})
    merged["channel"] = {k: v for k, v in info.items() if v != ""}
    if image:
        merged.setdefault("image", {}).update(image)
    _call(youtube.channels().update(part="brandingSettings", body={"id": channel_id, "brandingSettings": merged}))


def upload_banner(youtube, path: str, mimetype: str) -> str:
    """Upload a banner image; returns the URL to set as bannerExternalUrl."""
    from googleapiclient.http import MediaFileUpload

    res = _call(youtube.channelBanners().insert(media_body=MediaFileUpload(path, mimetype=mimetype, resumable=False)))
    if not res.get("url"):
        raise YouTubeError("YouTube didn't accept the banner image.")
    return res["url"]


def set_watermark(youtube, channel_id: str, path: str, mimetype: str, timing: str = "offsetFromEnd", offset_ms: int = 15000) -> None:
    """The small branding image (usually a subscribe button) shown on every video of the channel."""
    from googleapiclient.http import MediaFileUpload

    body = {"timing": {"type": timing, "offsetMs": int(offset_ms)}, "position": {"type": "corner", "cornerPosition": "topRight"}}
    if timing == "offsetFromStart" and offset_ms == 0:
        body["timing"]["durationMs"] = 0  # 0 = for the entire video
    _call(youtube.watermarks().set(channelId=channel_id, body=body, media_body=MediaFileUpload(path, mimetype=mimetype, resumable=False)))


def unset_watermark(youtube, channel_id: str) -> None:
    _call(youtube.watermarks().unset(channelId=channel_id))


def list_playlists(youtube) -> List[Dict[str, Any]]:
    res = _call(youtube.playlists().list(part="snippet,status,contentDetails", mine=True, maxResults=50))
    return [{
        "id": p["id"],
        "title": p["snippet"]["title"],
        "description": p["snippet"].get("description", ""),
        "privacy": p.get("status", {}).get("privacyStatus", ""),
        "count": p.get("contentDetails", {}).get("itemCount", 0),
    } for p in res.get("items") or []]


def create_playlist(youtube, title: str, description: str = "", privacy: str = "public") -> str:
    title = _clean(title)
    if not title:
        raise YouTubeError("The playlist needs a title.")
    body = {"snippet": {"title": title[:150], "description": _clean(description)[:5000]}, "status": {"privacyStatus": privacy}}
    return _call(youtube.playlists().insert(part="snippet,status", body=body))["id"]


def add_to_playlist(youtube, playlist_id: str, video_id: str) -> None:
    body = {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
    _call(youtube.playlistItems().insert(part="snippet", body=body))


# ---------- upload ----------

def to_utc_rfc3339(local: str, timezone: str) -> str:
    """'2026-10-25T19:00' in the channel's timezone -> '2026-10-25T13:30:00Z'."""
    when = dt.datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(timezone))
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(text: str) -> str:
    # YouTube rejects < and > in titles and descriptions.
    return (text or "").replace("<", "‹").replace(">", "›").strip()


clean_text = _clean


def tags_length(tags: List[str]) -> int:
    """Length of the tags as YouTube counts it: a phrase with a space is quoted, tags are comma separated."""
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0)


def fit_tags(tags: List[str], limit: int = TAGS_LIMIT) -> List[str]:
    """The tags in order, dropping any that would push the total past `limit`."""
    kept: List[str] = []
    for tag in (re.sub(r"[<>]", "", t).strip() for t in tags):
        if tag and tags_length(kept + [tag]) <= limit:
            kept.append(tag)
    return kept


def description_bytes(text: str) -> int:
    """YouTube's description limit is in UTF-8 bytes; a Devanagari letter takes 3."""
    return len((text or "").encode("utf-8"))


def fit_description(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    data = (text or "").encode("utf-8")
    if len(data) <= limit:
        return text or ""
    return data[:limit].decode("utf-8", errors="ignore").rstrip()


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
    kept = fit_tags(tags)
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
            "description": fit_description(_clean(description)),
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


# ---------- per-video details and metadata edits (AI Optimizer) ----------
# Edits send only the snippet part: status (privacy, Made for Kids) is never part of the body,
# so YouTube leaves it exactly as it is.

READ_RETRIES = 2  # reads and snippet updates are idempotent, so 5xx and rate-limit errors are retried


def video_details(youtube, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Live title, description, tags and settings of each video, 50 per request (1 unit each)."""
    out: Dict[str, Dict[str, Any]] = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for start in range(0, len(ids), 50):
        res = _call(youtube.videos().list(part="snippet,status,contentDetails,statistics", id=",".join(ids[start:start + 50])), retries=READ_RETRIES)
        for v in res.get("items") or []:
            sn, st, stats = v.get("snippet", {}), v.get("status", {}), v.get("statistics", {})
            out[v["id"]] = {
                "id": v["id"],
                "title": sn.get("title", ""),
                "description": sn.get("description", ""),
                "tags": list(sn.get("tags") or []),
                "category_id": sn.get("categoryId"),
                "default_language": sn.get("defaultLanguage"),
                "default_audio_language": sn.get("defaultAudioLanguage"),
                "published_at": sn.get("publishedAt"),
                "privacy": st.get("privacyStatus"),
                "made_for_kids": bool(st.get("madeForKids") or st.get("selfDeclaredMadeForKids")),
                "duration_s": _iso_duration(v.get("contentDetails", {}).get("duration", "")),
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
            }
    return out


def update_video_metadata(youtube, live: Dict[str, Any], title: str, description: str, tags: List[str]) -> Dict[str, Any]:
    """Replace a video's title, description and tags (50 units). `live` is its video_details() entry,
    read just before, so the category and languages are kept as they are."""
    title, description = _clean(title), _clean(description)
    if not title:
        raise YouTubeError("The video needs a title.")
    if len(title) > TITLE_LIMIT or description_bytes(description) > DESCRIPTION_LIMIT or tags_length(tags) > TAGS_LIMIT:
        raise YouTubeError("The title, description or tags are over YouTube's limits.")
    if not live.get("category_id"):
        raise YouTubeError("YouTube didn't say which category this video is in, so it can't be edited safely.")
    snippet = {"title": title, "description": description, "tags": list(tags), "categoryId": live["category_id"]}
    for key, field_name in (("default_language", "defaultLanguage"), ("default_audio_language", "defaultAudioLanguage")):
        if live.get(key):
            snippet[field_name] = live[key]
    res = _call(youtube.videos().update(part="snippet", body={"id": live["id"], "snippet": snippet}), retries=READ_RETRIES)
    sn = res.get("snippet", {})
    return {"title": sn.get("title", title), "description": sn.get("description", description), "tags": list(sn.get("tags") or tags)}


# ---------- channel analytics for the AI Optimizer ----------
# All read-only, from the YouTube Analytics API (its quota is separate from the Data API's 10,000 units).

def _report(analytics, start: dt.date, end: dt.date, **query) -> Dict[str, Any]:
    return _call(analytics.reports().query(ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(), **query), retries=READ_RETRIES)


def video_report(analytics, start: dt.date, end: dt.date, limit: int = 200) -> Dict[str, Dict[str, Any]]:
    """Per-video numbers for the period, keyed by video ID."""
    res = _report(analytics, start, end, dimensions="video", sort="-views", maxResults=min(limit, 200),
                  metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,shares,subscribersGained")
    return {r[0]: {"views": int(r[1]), "watch_minutes": float(r[2]), "avg_view_s": float(r[3]), "avg_view_pct": float(r[4]),
                   "likes": int(r[5]), "shares": int(r[6]), "subs_gained": int(r[7])} for r in res.get("rows") or []}


def traffic_sources(analytics, start: dt.date, end: dt.date) -> Dict[str, int]:
    """Views by traffic source type (YT_SEARCH, SHORTS, RELATED_VIDEO, SUBSCRIBER, EXT_URL, ...)."""
    res = _report(analytics, start, end, dimensions="insightTrafficSourceType", metrics="views", sort="-views")
    return {r[0]: int(r[1]) for r in res.get("rows") or []}


def content_types(analytics, start: dt.date, end: dt.date) -> Dict[str, Dict[str, float]]:
    """Views, watch time and % viewed split by Shorts / long-form / live."""
    res = _report(analytics, start, end, dimensions="creatorContentType", metrics="views,estimatedMinutesWatched,averageViewPercentage")
    return {str(r[0]).lower(): {"views": int(r[1]), "watch_minutes": float(r[2]), "avg_view_pct": float(r[3])} for r in res.get("rows") or []}


def video_daily_views(analytics, video_id: str, start: dt.date, end: dt.date) -> Dict[str, int]:
    """One video's views per day, {"YYYY-MM-DD": views}; days without views are missing."""
    res = _report(analytics, start, end, dimensions="day", metrics="views", filters=f"video=={video_id}", sort="day")
    return {r[0]: int(r[1]) for r in res.get("rows") or []}


def reach_metrics(analytics, start: dt.date, end: dt.date) -> Optional[Dict[str, Any]]:
    """Impressions and click-through rate, if the API serves them; None when it doesn't.

    Checked on a real channel on 2026-10-18: the Analytics API v2 answers "The query is not
    supported" for videoThumbnailImpressions / videoThumbnailImpressionsClickRate. Those
    numbers come only from the YouTube Reporting API (report type channel_reach_basic_a1),
    which needs a reporting job created once per channel and delivers daily CSV files
    about 48 hours later. This is where that source plugs in.
    """
    try:
        res = _report(analytics, start, end, metrics="videoThumbnailImpressions,videoThumbnailImpressionsClickRate")
    except YouTubeError:
        return None
    rows = res.get("rows") or []
    return {"impressions": int(rows[0][0]), "ctr_pct": float(rows[0][1])} if rows else None


def _iso_duration(value: str) -> Optional[float]:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return float(h * 3600 + mi * 60 + s)


# ---------- errors ----------

def _call(request, next_chunk: bool = False, retries: int = 0):
    """Execute a request, turning Google's errors into ones the hub can act on.

    `retries` > 0 lets the client library retry 5xx and rate-limit answers with backoff;
    only for requests that are safe to repeat.
    """
    import httplib2
    from google.auth.exceptions import RefreshError, TransportError
    from googleapiclient.errors import HttpError

    try:
        if next_chunk:
            return request.next_chunk()
        return request.execute(num_retries=retries) if retries else request.execute()
    except RefreshError:
        raise NotAuthorized("YouTube sign-in expired or was revoked. Reconnect the channel.")
    except HttpError as e:
        raise _translate(e)
    except (OSError, httplib2.HttpLib2Error, TransportError) as e:  # timeouts, DNS, dropped connections
        raise YouTubeError(f"Couldn't reach YouTube ({type(e).__name__}). Check the internet connection and try again.")


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
