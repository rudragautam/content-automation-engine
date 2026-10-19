"""AI Optimizer: fixed, rule-based checks of a channel's numbers. No AI, no network, no cost.

Input is the summary webapp.channel_audit gathers (per-video analytics, traffic sources,
daily totals, live metadata). Every finding carries the real numbers it rests on. Where
there are too few views to judge, the finding says "not enough data yet" instead of
guessing a reason.
"""

import datetime as dt
import re
import statistics
from typing import Any, Dict, List, Optional

MIN_CHANNEL_VIEWS = 100   # in the period, before traffic shares or trends mean anything
MIN_VIDEO_VIEWS = 30      # before one video's retention or engagement is judged
SETTLE_DAYS = 3           # a video's first days don't show where it ends up
LOW_PCT_SHORT, LOW_PCT_LONG = 70.0, 35.0
LOW_RECOMMENDED_SHARE = 25.0
LOW_SEARCH_SHARE = 5.0
TREND_DROP = 20.0
TITLE_SHORT, TITLE_LONG = 20, 70
DESCRIPTION_SHORT = 100
FEW_TAGS = 5
SEVERITY_POINTS = {"high": 20, "medium": 10, "low": 4, "info": 0}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# insightTrafficSourceType values that mean YouTube itself showed the video to someone.
RECOMMENDED = {"SUBSCRIBER": "Browse / home", "RELATED_VIDEO": "Suggested videos", "SHORTS": "Shorts feed"}
SOURCE_NAMES = {**RECOMMENDED, "YT_SEARCH": "YouTube search", "EXT_URL": "Outside links", "YT_CHANNEL": "Channel page",
                "PLAYLIST": "Playlists", "YT_PLAYLIST_PAGE": "Playlist pages", "NOTIFICATION": "Notifications",
                "HASHTAGS": "Hashtag pages", "END_SCREEN": "End screens", "NO_LINK_OTHER": "Direct / unknown",
                "YT_OTHER_PAGE": "Other YouTube pages", "SOUND_PAGE": "Sound pages", "ADVERTISING": "Ads"}


def finding(key: str, severity: str, title: str, detail: str, numbers: Dict[str, Any] = None, videos: List[str] = ()) -> Dict[str, Any]:
    return {"key": key, "severity": severity, "title": title, "detail": detail, "numbers": numbers or {}, "videos": list(videos)}


def not_enough(key: str, what: str, numbers: Dict[str, Any]) -> Dict[str, Any]:
    return finding(key, "info", f"Not enough data yet: {what}", "Too few views to judge this without guessing. Check again once the channel has more views.", numbers)


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _per_1000(count: float, views: float) -> float:
    return round(count / views * 1000, 1) if views else 0.0


def _published(v: Dict[str, Any]) -> Optional[dt.datetime]:
    value = v.get("published_at")
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(v: Dict[str, Any], today: dt.date) -> Optional[int]:
    p = _published(v)
    return (today - p.date()).days if p else None


def judged(videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Videos with enough views in the period to say anything about them."""
    return [v for v in videos if (v.get("views") or 0) >= MIN_VIDEO_VIEWS and v.get("avg_view_pct") is not None]


# ---------- the checks ----------

def check_volume(total_views: int, period: int) -> List[Dict[str, Any]]:
    if total_views < MIN_CHANNEL_VIEWS:
        return [not_enough("volume", "the channel as a whole",
                           {"views in period": total_views, "needed": MIN_CHANNEL_VIEWS, "days": period})]
    return []


def check_retention(videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for short, limit, label in ((True, LOW_PCT_SHORT, "Shorts"), (False, LOW_PCT_LONG, "long videos")):
        group = [v for v in videos if bool(v.get("is_short")) == short]
        if not group:
            continue
        rated = judged(group)
        if not rated:
            out.append(not_enough(f"retention_{'short' if short else 'long'}", f"how long viewers watch your {label}",
                                  {"videos": len(group), f"views needed per video": MIN_VIDEO_VIEWS}))
            continue
        views = sum(v["views"] for v in rated)
        avg = round(sum(v["avg_view_pct"] * v["views"] for v in rated) / views, 1)
        low = [v for v in rated if v["avg_view_pct"] < limit]
        numbers = {"average % viewed": avg, "target": limit, "videos judged": len(rated), "below target": len(low)}
        if avg < limit:
            out.append(finding(f"retention_{'short' if short else 'long'}", "high", f"Viewers leave your {label} early",
                               f"On average viewers watch {avg}% of your {label}; aim for {limit:.0f}% or more. "
                               "The first 3 seconds decide most of this.", numbers, [v["youtube_id"] for v in low]))
        elif low:
            out.append(finding(f"retention_{'short' if short else 'long'}_some", "medium" if len(low) >= len(rated) / 4 else "low",
                               f"{len(low)} of your {label} lose viewers early",
                               f"These are under {limit:.0f}% viewed while the channel averages {avg}%.", numbers, [v["youtube_id"] for v in low]))
        else:
            out.append(finding(f"retention_{'short' if short else 'long'}_ok", "info", f"Retention on your {label} is healthy",
                               f"Viewers watch {avg}% on average, so the content itself holds attention; reach is the thing to work on.", numbers))
    return out


def check_traffic(traffic: Dict[str, int]) -> List[Dict[str, Any]]:
    total = sum(traffic.values())
    if total < MIN_CHANNEL_VIEWS:
        return [not_enough("traffic", "where your views come from", {"views": total, "needed": MIN_CHANNEL_VIEWS})] if total else []
    shares = {SOURCE_NAMES.get(k, k.replace("_", " ").title()): _pct(n, total) for k, n in sorted(traffic.items(), key=lambda kv: -kv[1])}
    recommended = _pct(sum(traffic.get(k, 0) for k in RECOMMENDED), total)
    search = _pct(traffic.get("YT_SEARCH", 0), total)
    external = _pct(traffic.get("EXT_URL", 0), total)
    out = []
    if recommended < LOW_RECOMMENDED_SHARE:
        out.append(finding("recommended", "high", "YouTube is barely recommending your videos",
                           f"Only {recommended}% of views came from Browse, Suggested and the Shorts feed; under {LOW_RECOMMENDED_SHARE:.0f}% "
                           "means most viewers arrive another way (channel page, links). YouTube recommends videos that viewers click and keep watching.",
                           {"recommended %": recommended, **shares}))
    if search < LOW_SEARCH_SHARE:
        out.append(finding("search", "medium", "Almost nobody finds you through search",
                           f"{search}% of views came from YouTube search. Titles, descriptions and tags with the phrases viewers type are what search uses.",
                           {"search %": search, "search views": traffic.get("YT_SEARCH", 0)}))
    if external >= 30:
        out.append(finding("external", "info", "Many views come from links you share",
                           f"{external}% of views came from outside YouTube. That helps at the start, but these viewers rarely tell YouTube whom else to show the video to.",
                           {"outside links %": external}))
    if not out:
        out.append(finding("traffic_ok", "info", "Traffic sources look balanced", f"{recommended}% of views come from YouTube's recommendations.",
                           {"recommended %": recommended, **shares}))
    return out


def check_uploads(videos: List[Dict[str, Any]], today: dt.date, days: int = 90) -> List[Dict[str, Any]]:
    times = sorted(p for p in (_published(v) for v in videos if v.get("privacy") == "public") if p and (today - p.date()).days <= days)
    if len(times) < 2:
        return [not_enough("uploads", "your upload rhythm", {"public uploads in 90 days": len(times)})]
    out = []
    per_day: Dict[dt.date, int] = {}
    for t in times:
        per_day[t.date()] = per_day.get(t.date(), 0) + 1
    gaps = [(b.date() - a.date()).days for a, b in zip(times, times[1:])]
    since_last = (today - times[-1].date()).days
    numbers = {"uploads in 90 days": len(times), "days with uploads": len(per_day), "longest gap (days)": max(gaps),
               "median gap (days)": statistics.median(gaps), "days since last upload": since_last,
               "most in one day": max(per_day.values())}
    if since_last > 14:
        out.append(finding("stale", "high", "No new video for a while", f"The last upload was {since_last} days ago.", numbers))
    if max(per_day.values()) >= 4:
        out.append(finding("batches", "medium", "Videos are uploaded in batches",
                           f"Up to {max(per_day.values())} videos went public on the same day, across only {len(per_day)} days. "
                           "Videos released together compete for the same viewers; the same videos spread over the week each get their own test.",
                           numbers))
    if max(gaps) > 7 and max(gaps) > 2 * max(statistics.median(gaps), 1):
        out.append(finding("gaps", "medium", "Uploads are uneven",
                           f"The longest gap between uploads is {max(gaps)} days, against a usual {statistics.median(gaps):g}.", numbers))
    if not out:
        out.append(finding("uploads_ok", "info", "Uploads are regular", f"{len(times)} uploads in 90 days, usually {statistics.median(gaps):g} days apart.", numbers))
    return out


def check_metadata(videos: List[Dict[str, Any]], playlists: Optional[int]) -> List[Dict[str, Any]]:
    public = [v for v in videos if v.get("privacy") in ("public", "unlisted")]
    if not public:
        return []
    weak = {
        "titles_short": ([v for v in public if len(v["title"]) < TITLE_SHORT], f"titles under {TITLE_SHORT} characters"),
        "titles_long": ([v for v in public if len(v["title"]) > TITLE_LONG], f"titles over {TITLE_LONG} characters (cut off in the feed)"),
        "no_description": ([v for v in public if len((v.get("description") or "").strip()) < DESCRIPTION_SHORT], f"a description under {DESCRIPTION_SHORT} characters"),
        "few_tags": ([v for v in public if len(v.get("tags") or []) < FEW_TAGS], f"fewer than {FEW_TAGS} tags"),
        "no_hashtags": ([v for v in public if "#" not in (v.get("description") or "") + v["title"]], "no hashtags"),
    }
    out = []
    for key, (bad, what) in weak.items():
        if not bad:
            continue
        share = _pct(len(bad), len(public))
        severity = "high" if share >= 75 and key in ("no_description", "few_tags") else "medium" if share >= 40 else "low"
        out.append(finding(key, severity, f"{len(bad)} of {len(public)} videos have {what}",
                           "Search and suggestions read the title, description and tags to decide who a video is for.",
                           {"videos": len(bad), "of": len(public), "%": share}, [v["youtube_id"] for v in bad]))
    if playlists == 0:
        out.append(finding("no_playlists", "medium", "The channel has no playlists",
                           "Playlists keep viewers watching one video after another and give YouTube more places to show your videos.", {"playlists": 0}))
    return out


def check_formats(videos: List[Dict[str, Any]], content: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    shorts = [v for v in videos if v.get("is_short") and v.get("privacy") == "public"]
    longs = [v for v in videos if not v.get("is_short") and v.get("privacy") == "public"]
    if len(shorts) < 3 or len(longs) < 3:
        return []
    avg_s = sum(v.get("views") or 0 for v in shorts) / len(shorts)
    avg_l = sum(v.get("views") or 0 for v in longs) / len(longs)
    numbers = {"Shorts": len(shorts), "avg views per Short": round(avg_s), "long videos": len(longs), "avg views per long video": round(avg_l)}
    if content:
        numbers.update({f"{k} views": int(v["views"]) for k, v in content.items()})
    if max(avg_s, avg_l) >= 3 * max(min(avg_s, avg_l), 1) and max(avg_s, avg_l) >= MIN_VIDEO_VIEWS:
        better, worse = ("Shorts", "long videos") if avg_s > avg_l else ("long videos", "Shorts")
        return [finding("formats", "medium", f"Your {better} do far better than your {worse}",
                        f"An average {better[:-1] if better.endswith('s') else better} gets {round(max(avg_s, avg_l))} views against {round(min(avg_s, avg_l))}. "
                        f"Put more effort where viewers already respond, or rework the {worse}.", numbers)]
    return []


def check_trend(daily: List[Dict[str, Any]], today: dt.date, period: int = 28) -> List[Dict[str, Any]]:
    # YouTube's daily numbers arrive 2-3 days late; ending at the last day it reported keeps
    # those missing days from looking like a drop.
    end = min(today, dt.date.fromisoformat(max(d["date"] for d in daily)) + dt.timedelta(days=1)) if daily else today
    start, prev = end - dt.timedelta(days=period), end - dt.timedelta(days=2 * period)
    cur = [d for d in daily if start.isoformat() <= d["date"] < end.isoformat()]
    old = [d for d in daily if prev.isoformat() <= d["date"] < start.isoformat()]
    def total(rows, key):
        return sum(r[key] for r in rows)
    numbers = {"views now": total(cur, "views"), "views before": total(old, "views"),
               "watch hours now": round(total(cur, "watch_minutes") / 60, 1), "watch hours before": round(total(old, "watch_minutes") / 60, 1),
               "net subscribers now": total(cur, "subs_gained") - total(cur, "subs_lost"),
               "net subscribers before": total(old, "subs_gained") - total(old, "subs_lost")}
    if numbers["views before"] < MIN_CHANNEL_VIEWS / 2:
        return [not_enough("trend", f"the trend against the previous {period} days", numbers)]
    change = round((numbers["views now"] - numbers["views before"]) / numbers["views before"] * 100, 1)
    numbers["change %"] = change
    if change <= -TREND_DROP:
        return [finding("trend_down", "high" if change <= -40 else "medium", f"Views fell {abs(change)}% against the previous {period} days",
                        f"{numbers['views now']} views now against {numbers['views before']} before.", numbers)]
    if change >= TREND_DROP:
        return [finding("trend_up", "info", f"Views rose {change}% against the previous {period} days",
                        f"{numbers['views now']} views now against {numbers['views before']} before. Look at what changed and keep doing it.", numbers)]
    return [finding("trend_flat", "info", f"Views are steady ({change:+}%)", f"{numbers['views now']} views now against {numbers['views before']} before.", numbers)]


def check_engagement(videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rated = judged(videos)
    if not rated:
        return []
    views = sum(v["views"] for v in rated)
    numbers = {"likes per 1,000 views": _per_1000(sum(v.get("likes") or 0 for v in rated), views),
               "shares per 1,000 views": _per_1000(sum(v.get("shares") or 0 for v in rated), views),
               "subscribers per 1,000 views": _per_1000(sum(v.get("subs_gained") or 0 for v in rated), views)}
    if numbers["likes per 1,000 views"] < 15:
        return [finding("engagement", "low", "Few viewers like the videos",
                        f"{numbers['likes per 1,000 views']} likes per 1,000 views on the videos with enough data.", numbers)]
    return [finding("engagement_ok", "info", "Engagement", f"{numbers['likes per 1,000 views']} likes and {numbers['shares per 1,000 views']} shares per 1,000 views.", numbers)]


def compare_top_bottom(videos: List[Dict[str, Any]], today: dt.date, tz=None) -> List[Dict[str, Any]]:
    """What the 3 best videos have in common that the 3 weakest don't."""
    settled = [v for v in videos if v.get("privacy") == "public" and (_age_days(v, today) or 0) >= SETTLE_DAYS]
    if len(settled) < 6 or sum(v.get("views") or 0 for v in settled) < MIN_CHANNEL_VIEWS:
        return [not_enough("top_bottom", "what your best videos have in common", {"settled public videos": len(settled), "needed": 6})]
    ranked = sorted(settled, key=lambda v: (-(v.get("views") or 0), v["title"]))
    top, bottom = ranked[:3], ranked[-3:]

    def traits(group):
        hours = [(_published(v).astimezone(tz) if tz else _published(v)).hour for v in group if _published(v)]
        pcts = [v["avg_view_pct"] for v in group if v.get("avg_view_pct") is not None]
        return {
            "avg views": round(sum(v.get("views") or 0 for v in group) / len(group)),
            "title length": round(sum(len(v["title"]) for v in group) / len(group)),
            "titles in Devanagari": sum(1 for v in group if DEVANAGARI.search(v["title"])),
            "description length": round(sum(len(v.get("description") or "") for v in group) / len(group)),
            "tags": round(sum(len(v.get("tags") or []) for v in group) / len(group), 1),
            "length (s)": round(sum(v.get("duration_s") or 0 for v in group) / len(group)),
            "% viewed": round(sum(pcts) / len(pcts), 1) if pcts else None,
            "publish hour": statistics.median(hours) if hours else None,
        }

    t, b = traits(top), traits(bottom)
    differences = []
    for key in t:
        if key == "avg views" or t[key] is None or b[key] is None:
            continue
        hi, lo = max(t[key], b[key]), min(t[key], b[key])
        if (key == "publish hour" and abs(t[key] - b[key]) >= 3) or (key != "publish hour" and hi > 0 and (hi - lo) / hi >= 0.25):
            differences.append(f"{key}: top {t[key]} vs bottom {b[key]}")
    detail = ("Top 3: " + "; ".join(f"{v['title']} ({v.get('views') or 0})" for v in top) + ". Bottom 3: " +
              "; ".join(f"{v['title']} ({v.get('views') or 0})" for v in bottom) + ". " +
              ("Clear differences: " + "; ".join(differences) + "." if differences else "No clear difference in titles, length or timing; the topic itself may be what viewers pick."))
    return [finding("top_bottom", "info", "Your best 3 videos against your weakest 3", detail,
                    {**{f"top {k}": v for k, v in t.items()}, **{f"bottom {k}": v for k, v in b.items()}},
                    [v["youtube_id"] for v in top + bottom])]


# ---------- per video, score, all together ----------

def video_findings(v: Dict[str, Any], channel_avg_pct: Optional[float], median_views: float) -> List[str]:
    """Short lines with numbers about one video, for its Gemini prompt and its card."""
    out = []
    views = v.get("views") or 0
    if views < MIN_VIDEO_VIEWS:
        out.append(f"Not enough data yet: {views} views in the period (needs {MIN_VIDEO_VIEWS} to judge retention).")
    else:
        pct = v.get("avg_view_pct")
        if pct is not None:
            limit = LOW_PCT_SHORT if v.get("is_short") else LOW_PCT_LONG
            note = "below" if pct < limit else "at or above"
            out.append(f"{pct}% viewed on average, {note} the {limit:.0f}% target" + (f"; channel average {channel_avg_pct}%" if channel_avg_pct else "") + ".")
        out.append(f"{_per_1000(v.get('likes') or 0, views)} likes and {_per_1000(v.get('shares') or 0, views)} shares per 1,000 views.")
    if median_views:
        out.append(f"{views} views in the period against a channel median of {median_views:g} per video.")
    if len(v["title"]) < TITLE_SHORT or len(v["title"]) > TITLE_LONG:
        out.append(f"Title is {len(v['title'])} characters (aim for {TITLE_SHORT}-{TITLE_LONG}).")
    if len((v.get("description") or "").strip()) < DESCRIPTION_SHORT:
        out.append(f"Description is {len((v.get('description') or '').strip())} characters (aim for {DESCRIPTION_SHORT}+ with search phrases).")
    if len(v.get("tags") or []) < FEW_TAGS:
        out.append(f"{len(v.get('tags') or [])} tags (aim for 8-15).")
    return out


def health_score(findings: List[Dict[str, Any]]) -> Optional[int]:
    judgeable = [f for f in findings if not f["title"].startswith("Not enough data")]
    if not judgeable:
        return None
    return max(0, 100 - sum(SEVERITY_POINTS[f["severity"]] for f in judgeable))


def run_checks(data: Dict[str, Any]) -> Dict[str, Any]:
    """All checks on one channel's data: {"findings", "score", "numbers"}."""
    today, period = data["today"], data.get("period", 28)
    videos = data["videos"]
    total = sum(data.get("traffic", {}).values()) or sum(v.get("views") or 0 for v in videos)
    findings = []
    findings += check_volume(total, period)
    findings += check_trend(data.get("daily", []), today, period)
    findings += check_traffic(data.get("traffic", {}))
    findings += check_retention(videos)
    findings += check_uploads(videos, today)
    findings += check_metadata(videos, data.get("playlists"))
    findings += check_formats(videos, data.get("content", {}))
    findings += check_engagement(videos)
    findings += compare_top_bottom(videos, today, data.get("tz"))
    findings.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])
    rated = judged(videos)
    views = sum(v["views"] for v in rated)
    numbers = {
        "views": total,
        "avg_view_pct": round(sum(v["avg_view_pct"] * v["views"] for v in rated) / views, 1) if views else None,
        "recommended_pct": _pct(sum(data.get("traffic", {}).get(k, 0) for k in RECOMMENDED), sum(data.get("traffic", {}).values())),
        "search_pct": _pct(data.get("traffic", {}).get("YT_SEARCH", 0), sum(data.get("traffic", {}).values())),
        "likes_per_1000": _per_1000(sum(v.get("likes") or 0 for v in rated), views),
        "videos": len(videos),
    }
    return {"findings": findings, "score": health_score(findings), "numbers": numbers}


def weakest(videos: List[Dict[str, Any]], today: dt.date, limit: int) -> List[Dict[str, Any]]:
    """Public videos to optimize first: fewest views per day since publishing, settled ones before brand-new ones."""
    public = [v for v in videos if v.get("privacy") in ("public", "unlisted") and v.get("youtube_id")]

    def rate(v):
        age = max(_age_days(v, today) or 1, 1)
        return (age < SETTLE_DAYS, (v.get("lifetime_views") or v.get("views") or 0) / age)
    ranked = sorted(public, key=rate)
    return ranked if not limit else ranked[:limit]
