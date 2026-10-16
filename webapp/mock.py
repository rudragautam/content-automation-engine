"""Mock channels, stats and videos so the hub is usable before YouTube is connected.

Seeded from a fixed random seed, so the numbers are stable between runs.
Every mock row is flagged is_mock = 1 and the UI labels it as mock data.
"""

import datetime as dt
import math
import random

from webapp import timeutil

# (name, handle, niche, subscribers, publish slots, connection)
CHANNELS = [
    ("Focus Daily", "@focusdaily", "focus_habits", 48200, ["09:00", "19:00"], "connected"),
    ("Mind Over Phone", "@mindoverphone", "focus_habits", 6100, ["20:00"], "connected"),
    ("Focus Habits Hindi", "@focushabitshindi", "focus_habits", 15400, ["19:30"], "connected"),
    ("Geeta Gyaan", "@geetagyaan", "geeta_gyaan", 132000, ["06:00", "19:00"], "connected"),
    ("Krishna Vani", "@krishnavani", "geeta_gyaan", 27800, ["06:30"], "connected"),
    ("Quiz Time", "@quiztime", "general_quiz", 39500, ["13:00", "20:00"], "connected"),
    ("GK Battle Hindi", "@gkbattlehindi", "general_quiz", 21300, ["18:00"], "expired"),
    ("Science Quiz Lab", "@sciencequizlab", "science_quiz", 9800, ["17:00"], "connected"),
    ("Space Quiz", "@spacequiz", "science_quiz", 2400, ["21:00"], "connected"),
    ("Science Stories", "@sciencestories", "science_story", 58700, ["12:00", "21:00"], "connected"),
    ("Cosmos Shorts", "@cosmosshorts", "science_story", 11900, ["21:30"], "connected"),
    ("Bharat Kathayein", "@bharatkathayein", "indian_traditional_story", 44100, ["19:00"], "connected"),
    ("Folk Tales India", "@folktalesindia", "indian_traditional_story", 3900, ["18:30"], "connected"),
    ("Heritage of India", "@heritageofindia", "indian_heritage_story", 17600, ["11:00"], "connected"),
    ("Crime Files", "@crimefiles", "crime_files", 88300, ["21:00"], "connected"),
    ("Crime Files Hindi", "@crimefileshindi", "crime_files", 35200, ["22:00"], "connected"),
    ("Mystery Archives", "@mysteryarchives", "crime_files", 800, ["22:30"], "not_connected"),
    ("Neural Intelligence", "@neuralintel", "ai_neural_intelligence", 23400, ["10:00"], "connected"),
    ("Digital Future", "@digitalfuture", "ai_digital_future", 12700, ["10:30", "18:00"], "connected"),
    ("AI Explained Daily", "@aiexplaineddaily", "ai_digital_future", 5300, ["09:30"], "connected"),
]

TITLES = {
    "focus_habits": ["5 Habits That Ruin Your Focus", "Why You Can't Concentrate", "The 2-Minute Focus Reset", "Stop Checking Your Phone", "Deep Work in 4 Steps", "Morning Habits of Focused People", "Why Multitasking Fails", "Sleep and Focus Explained"],
    "geeta_gyaan": ["गीता के 4 सूत्र", "कर्म का रहस्य", "मन को स्थिर कैसे करें", "क्रोध पर विजय", "सच्ची शांति का मार्ग", "कृष्ण का संदेश", "धैर्य की शक्ति", "ज्ञान और कर्म"],
    "general_quiz": ["Can You Score 4/4?", "Only Geniuses Get This Right", "Capital Cities Quiz", "History Quiz in 30 Seconds", "Guess the Planet", "India GK Challenge", "Famous Inventors Quiz", "Animal Facts Quiz"],
    "science_quiz": ["Think You Know Science?", "Physics in 4 Questions", "Space Quiz Challenge", "Human Body Quiz", "Chemistry Basics Quiz", "Solar System Quiz", "Biology Quick Quiz", "Light and Sound Quiz"],
    "science_story": ["How the Sky Became Science", "The Day We Measured the Earth", "Why the Sky Is Blue", "The Story of Gravity", "How Vaccines Were Born", "The First Photograph of a Black Hole", "Where Does Gold Come From?", "The Clock in Your Cells"],
    "indian_traditional_story": ["Why We Light Diyas on Diwali", "The Story of Raksha Bandhan", "Eklavya's Lesson", "The Wisdom of Birbal", "Why We Celebrate Holi", "The Legend of Onam", "Tenali Raman and the Thief", "The Tale of Savitri"],
    "indian_heritage_story": ["Konark: A Chariot of Stone", "The Iron Pillar That Won't Rust", "Hampi's Musical Pillars", "Jantar Mantar's Giant Sundial", "The Stepwells of Gujarat", "Ajanta's Painted Caves", "The Engineering of Kailasa", "Nalanda: The Ancient University"],
    "crime_files": ["The Night the City Went Silent", "The Clue on the Wall", "A Case That Made No Sense", "The Missing Hour", "The Last Phone Call", "Footprints in the Rain", "The Locked Room", "The Witness Who Vanished"],
    "ai_neural_intelligence": ["How AI Actually Works", "What Is a Neural Network?", "Why AI Makes Mistakes", "AI and Your Job", "How Chatbots Learn", "The Data Behind AI", "Can AI Be Creative?", "AI Explained in 60 Seconds"],
    "ai_digital_future": ["4 Shifts in the Next Era of AI", "What Are AI Agents?", "Robots Are Leaving the Lab", "The Future of Work With AI", "AI in Medicine", "Smart Cities Explained", "The Next Web", "AI in 2030"],
}

DAYS = 90


def seed(conn, now: dt.datetime = None) -> None:
    """Fill an empty database with mock data. Does nothing if channels exist or mock data was removed."""
    from webapp.db import get_setting

    if conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] or get_setting(conn, "mock_removed"):
        return
    rng = random.Random(7)
    now = now or timeutil.now_local()
    today = now.date()

    for name, handle, niche, subs, slots, connection in CHANNELS:
        created = today - dt.timedelta(days=rng.randint(120, 700))
        cur = conn.execute(
            "INSERT INTO channels (name, handle, niche, youtube_channel_id, connection, subscribers, created_at, is_mock) VALUES (?,?,?,?,?,?,?,1)",
            (name, handle, niche, None if connection == "not_connected" else "UC" + "".join(rng.choices("abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ0123456789_-", k=22)), connection, subs, created.isoformat()),
        )
        channel_id = cur.lastrowid
        conn.executemany("INSERT INTO channel_slots (channel_id, time) VALUES (?, ?)", [(channel_id, s) for s in slots])
        _seed_stats(conn, rng, channel_id, subs, today)
        if connection != "not_connected":
            _seed_published(conn, rng, channel_id, niche, subs, slots, today)
            _seed_upcoming(conn, rng, channel_id, niche, slots, now)

    failed = conn.execute("SELECT id FROM videos WHERE status = 'scheduled' ORDER BY publish_at LIMIT 1 OFFSET 3").fetchone()
    if failed:
        conn.execute("UPDATE videos SET status = 'failed', error = 'YouTube upload failed: daily API quota exceeded (mock)' WHERE id = ?", (failed[0],))
    conn.execute("INSERT OR REPLACE INTO quota_usage (date, units) VALUES (?, ?)", (today.isoformat(), 6550))


def _seed_stats(conn, rng, channel_id, subs, today):
    base = max(80, subs * rng.uniform(0.03, 0.07))
    growth = rng.uniform(-0.15, 0.6)  # change across the 90 days
    rows = []
    for d in range(DAYS, 0, -1):
        day = today - dt.timedelta(days=d)
        t = 1 - d / DAYS
        weekend = 1.18 if day.weekday() >= 5 else 1.0
        wave = 1 + 0.08 * math.sin(d / 5.0)
        spike = rng.uniform(1.8, 3.2) if rng.random() < 0.03 else 1.0  # an occasional video takes off
        views = int(base * (1 + growth * t) * weekend * wave * spike * rng.uniform(0.82, 1.18))
        watch = int(views * rng.uniform(0.32, 0.45))
        gained = int(views * rng.uniform(0.003, 0.007))
        lost = int(gained * rng.uniform(0.08, 0.25))
        rows.append((channel_id, day.isoformat(), views, watch, gained, lost))
    conn.executemany("INSERT INTO daily_stats VALUES (?,?,?,?,?,?)", rows)


def _seed_published(conn, rng, channel_id, niche, subs, slots, today):
    rows = []
    titles = TITLES[niche]
    for d in range(DAYS, 0, -1):
        day = today - dt.timedelta(days=d)
        for slot in slots:
            if rng.random() < 0.15:  # not every slot gets a video
                continue
            hour = int(slot[:2])
            # Evening and weekend uploads do a little better, so the timing heatmap has a pattern.
            boost = (1.35 if hour >= 18 else 1.0) * (1.2 if day.weekday() >= 5 else 1.0)
            views = int(rng.lognormvariate(math.log(max(50, subs * 0.04)), 0.9) * boost)
            title = f"{rng.choice(titles)}"
            rows.append((
                channel_id, f"M-{channel_id}-{len(rows)+1:04d}", title, "", "", "published",
                f"{day.isoformat()}T{slot}", round(rng.uniform(18, 45), 1), views,
                int(views * rng.uniform(0.02, 0.06)), int(views * rng.uniform(0.001, 0.006)),
                round(rng.uniform(55, 98), 1), f"{day.isoformat()}T08:00",
            ))
    conn.executemany(
        "INSERT INTO videos (channel_id, video_ref, title, description, tags, status, publish_at, duration_s, views, likes, comments, avg_view_pct, created_at, is_mock) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)", rows)


def _seed_upcoming(conn, rng, channel_id, niche, slots, now):
    """Scheduled videos for the next days; some channels run low on purpose."""
    days_ahead = rng.choice([1, 2, 4, 6, 7, 7])
    rows = []
    for d in range(0, days_ahead + 1):
        day = now.date() + dt.timedelta(days=d)
        for slot in slots:
            when = dt.datetime.fromisoformat(f"{day.isoformat()}T{slot}")
            if when <= now.replace(tzinfo=None):
                continue
            rows.append((channel_id, f"M-{channel_id}-U{len(rows)+1:03d}", rng.choice(TITLES[niche]), "", "", "scheduled",
                         when.strftime("%Y-%m-%dT%H:%M"), round(rng.uniform(18, 45), 1), now.strftime("%Y-%m-%dT%H:%M")))
    conn.executemany(
        "INSERT INTO videos (channel_id, video_ref, title, description, tags, status, publish_at, duration_s, created_at, is_mock) "
        "VALUES (?,?,?,?,?,?,?,?,?,1)", rows)
