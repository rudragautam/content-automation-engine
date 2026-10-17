"""SQLite storage for the content hub.

Everything the hub shows or edits lives here: channels and their publish
slots, the video queue, daily channel stats, content uploads and the audio
library. Until YouTube is connected, channels, stats and published videos
are mock rows written by webapp.mock.
"""

import os
import sqlite3
from contextlib import contextmanager

HUB_DIR = os.environ.get("CONTENT_HUB_DIR", os.path.join("output", "hub"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    handle TEXT NOT NULL,
    niche TEXT NOT NULL,
    youtube_channel_id TEXT,
    connection TEXT NOT NULL,          -- connected | expired | not_connected
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    subscribers INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    is_mock INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS channel_slots (
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    time TEXT NOT NULL,                -- HH:MM in the channel's timezone
    PRIMARY KEY (channel_id, time)
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    video_ref TEXT NOT NULL,           -- video_id from the sheet, or generated
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,              -- ready | rendering | rendered | uploading | scheduled | published | failed
    publish_at TEXT,                   -- local time YYYY-MM-DDTHH:MM
    duration_s REAL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    avg_view_pct REAL,
    content_json TEXT,
    upload_id INTEGER REFERENCES uploads(id),
    video_path TEXT,
    audio_id INTEGER,
    error TEXT,
    created_at TEXT NOT NULL,
    is_mock INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS videos_channel_status ON videos(channel_id, status);
CREATE INDEX IF NOT EXISTS videos_publish_at ON videos(publish_at);
CREATE TABLE IF NOT EXISTS daily_stats (
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    views INTEGER NOT NULL,
    watch_minutes INTEGER NOT NULL,
    subs_gained INTEGER NOT NULL,
    subs_lost INTEGER NOT NULL,
    PRIMARY KEY (channel_id, date)
);
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY,
    niche TEXT NOT NULL,
    channel_id INTEGER REFERENCES channels(id),
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    videos_added INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audio (
    id INTEGER PRIMARY KEY,
    niche TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,            -- stored name on disk
    licence TEXT NOT NULL DEFAULT '',
    duration_s REAL,
    uploaded_at TEXT NOT NULL,
    last_used_at TEXT,
    times_used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quota_usage (
    date TEXT PRIMARY KEY,
    units INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    niche TEXT NOT NULL,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    count INTEGER NOT NULL,
    instructions TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL,
    status TEXT NOT NULL,              -- generating | ready | failed | queued | discarded
    rows_json TEXT,                    -- every generated video as sheet-style rows
    rejected_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after the first release; init() adds any that an older database lacks.
MIGRATIONS = {
    "videos": [("youtube_video_id", "TEXT"), ("upload_progress", "REAL")],
    "channels": [("last_synced_at", "TEXT"), ("setup_json", "TEXT"), ("angle", "TEXT"), ("google_account", "TEXT")],
}


def db_path() -> str:
    return os.path.join(HUB_DIR, "hub.db")


def connect() -> sqlite3.Connection:
    os.makedirs(HUB_DIR, exist_ok=True)
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def get_setting(conn, key: str, default: str = None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
