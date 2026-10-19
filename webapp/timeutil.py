"""Times in the hub are stored as naive local strings (YYYY-MM-DDTHH:MM) in the hub's timezone."""

import datetime as dt
import os
from zoneinfo import ZoneInfo

TIMEZONE = os.environ.get("CONTENT_HUB_TZ", "Asia/Kolkata")


def now_local() -> dt.datetime:
    return dt.datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None, second=0, microsecond=0)


def parse(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


def fmt(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")
