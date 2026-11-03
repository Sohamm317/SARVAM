"""SQLite database setup and queries for the language coach."""

import sqlite3
import os
import time
from contextlib import contextmanager

DATABASE_PATH = os.environ.get("DATABASE_PATH", "persona_chat.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
    id              TEXT PRIMARY KEY,
    timezone        TEXT DEFAULT 'Asia/Kolkata',
    target_language TEXT DEFAULT 'hi-IN',
    daily_goal      INTEGER DEFAULT 20,
    voice_id        TEXT,
    voice_language  TEXT,
    consent_ts      REAL,
    xp              INTEGER DEFAULT 0,
    level           INTEGER DEFAULT 1,
    streak_current  INTEGER DEFAULT 0,
    streak_longest  INTEGER DEFAULT 0,
    streak_freezes  INTEGER DEFAULT 0,
    last_goal_date  TEXT,
    created_at      REAL
);

CREATE TABLE IF NOT EXISTS xp_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id TEXT NOT NULL,
    kind       TEXT NOT NULL,
    amount     INTEGER NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (learner_id) REFERENCES learners(id)
);

CREATE TABLE IF NOT EXISTS daily_progress (
    learner_id    TEXT NOT NULL,
    date          TEXT NOT NULL,
    xp            INTEGER DEFAULT 0,
    words_learned INTEGER DEFAULT 0,
    words_reviewed INTEGER DEFAULT 0,
    goal_met      INTEGER DEFAULT 0,
    PRIMARY KEY (learner_id, date),
    FOREIGN KEY (learner_id) REFERENCES learners(id)
);

CREATE TABLE IF NOT EXISTS words (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id    TEXT NOT NULL,
    language_code TEXT NOT NULL,
    text          TEXT NOT NULL,
    romanized     TEXT,
    meaning       TEXT NOT NULL,
    leitner_box   INTEGER DEFAULT 0,
    next_review   TEXT,
    times_heard   INTEGER DEFAULT 0,
    created_at    REAL NOT NULL,
    FOREIGN KEY (learner_id) REFERENCES learners(id),
    UNIQUE (learner_id, language_code, text)
);

CREATE TABLE IF NOT EXISTS achievements (
    learner_id TEXT NOT NULL,
    badge_code TEXT NOT NULL,
    unlocked_at REAL NOT NULL,
    PRIMARY KEY (learner_id, badge_code),
    FOREIGN KEY (learner_id) REFERENCES learners(id)
);

CREATE TABLE IF NOT EXISTS daily_quests (
    learner_id  TEXT NOT NULL,
    date        TEXT NOT NULL,
    quest_code  TEXT NOT NULL,
    target      INTEGER NOT NULL,
    progress    INTEGER DEFAULT 0,
    completed   INTEGER DEFAULT 0,
    PRIMARY KEY (learner_id, date, quest_code),
    FOREIGN KEY (learner_id) REFERENCES learners(id)
);
"""


def get_db_path():
    configured = os.environ.get("DATABASE_PATH")
    if configured:
        return configured
    # Vercel serverless functions have a read-only filesystem except /tmp
    if os.environ.get("VERCEL"):
        return "/tmp/persona_chat.db"
    return "persona_chat.db"


def init_db():
    """Create all tables if they don't exist."""
    conn = sqlite3.connect(get_db_path())
    conn.executescript(SCHEMA)
    conn.close()


@contextmanager
def get_conn():
    """Yield a sqlite3 connection with row_factory set, auto-commit on success."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Learner CRUD ──

def ensure_learner(learner_id: str) -> dict:
    """Get or create a learner row. Returns a dict."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM learners WHERE id = ?", (learner_id,)).fetchone()
        if row:
            return dict(row)
        now = time.time()
        conn.execute(
            "INSERT INTO learners (id, created_at) VALUES (?, ?)",
            (learner_id, now),
        )
        row = conn.execute("SELECT * FROM learners WHERE id = ?", (learner_id,)).fetchone()
        return dict(row)


def update_learner(learner_id: str, **fields) -> dict:
    """Update arbitrary columns on a learner row."""
    if not fields:
        return ensure_learner(learner_id)
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [learner_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE learners SET {sets} WHERE id = ?", vals)
        row = conn.execute("SELECT * FROM learners WHERE id = ?", (learner_id,)).fetchone()
        return dict(row)


def get_learner(learner_id: str) -> dict | None:
    """Get a learner row or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM learners WHERE id = ?", (learner_id,)).fetchone()
        return dict(row) if row else None


# ── XP Events ──

def add_xp_event(learner_id: str, kind: str, amount: int):
    """Insert an XP event and update the learner's total XP."""
    now = time.time()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO xp_events (learner_id, kind, amount, created_at) VALUES (?, ?, ?, ?)",
            (learner_id, kind, amount, now),
        )
        conn.execute(
            "UPDATE learners SET xp = xp + ? WHERE id = ?",
            (amount, learner_id),
        )


# ── Daily Progress ──

def get_daily_progress(learner_id: str, date_str: str) -> dict:
    """Get or create the daily progress row for a date (YYYY-MM-DD)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_progress WHERE learner_id = ? AND date = ?",
            (learner_id, date_str),
        ).fetchone()
        if row:
            return dict(row)
        conn.execute(
            "INSERT INTO daily_progress (learner_id, date) VALUES (?, ?)",
            (learner_id, date_str),
        )
        row = conn.execute(
            "SELECT * FROM daily_progress WHERE learner_id = ? AND date = ?",
            (learner_id, date_str),
        ).fetchone()
        return dict(row)


def increment_daily(learner_id: str, date_str: str, **increments):
    """Increment daily counters. e.g. increment_daily(lid, d, xp=5, words_learned=1)."""
    get_daily_progress(learner_id, date_str)  # ensure row
    sets = ", ".join(f"{k} = {k} + ?" for k in increments)
    vals = list(increments.values()) + [learner_id, date_str]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE daily_progress SET {sets} WHERE learner_id = ? AND date = ?",
            vals,
        )


def mark_goal_met(learner_id: str, date_str: str):
    """Mark daily goal as met."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE daily_progress SET goal_met = 1 WHERE learner_id = ? AND date = ?",
            (learner_id, date_str),
        )


# ── Words ──

def save_word(learner_id: str, language_code: str, text: str,
              romanized: str | None, meaning: str) -> dict:
    """Save a vocab word. Returns the word dict. Upsert on conflict."""
    now = time.time()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO words (learner_id, language_code, text, romanized, meaning, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (learner_id, language_code, text) DO UPDATE SET
                   romanized = excluded.romanized,
                   meaning = excluded.meaning""",
            (learner_id, language_code, text, romanized, meaning, now),
        )
        row = conn.execute(
            "SELECT * FROM words WHERE learner_id = ? AND language_code = ? AND text = ?",
            (learner_id, language_code, text),
        ).fetchone()
        return dict(row)


def get_words(learner_id: str, language_code: str | None = None) -> list[dict]:
    """Get all saved words, optionally filtered by language."""
    with get_conn() as conn:
        if language_code:
            rows = conn.execute(
                "SELECT * FROM words WHERE learner_id = ? AND language_code = ? ORDER BY created_at DESC",
                (learner_id, language_code),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM words WHERE learner_id = ? ORDER BY created_at DESC",
                (learner_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_words_for_review(learner_id: str, date_str: str, limit: int = 10) -> list[dict]:
    """Get words due for review (next_review <= date or NULL, leitner_box < 5)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM words
               WHERE learner_id = ? AND leitner_box < 5
                 AND (next_review IS NULL OR next_review <= ?)
               ORDER BY leitner_box ASC, RANDOM()
               LIMIT ?""",
            (learner_id, date_str, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def update_word_review(word_id: int, correct: bool, next_review: str):
    """Update a word after a review answer."""
    with get_conn() as conn:
        if correct:
            conn.execute(
                "UPDATE words SET leitner_box = MIN(leitner_box + 1, 5), next_review = ? WHERE id = ?",
                (next_review, word_id),
            )
        else:
            conn.execute(
                "UPDATE words SET leitner_box = MAX(leitner_box - 1, 0), next_review = ? WHERE id = ?",
                (next_review, word_id),
            )


def increment_word_heard(word_id: int):
    """Increment the times_heard counter for a word."""
    with get_conn() as conn:
        conn.execute("UPDATE words SET times_heard = times_heard + 1 WHERE id = ?", (word_id,))


def count_words(learner_id: str) -> int:
    """Total number of saved words for a learner."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM words WHERE learner_id = ?", (learner_id,)
        ).fetchone()
        return row["cnt"]


def count_languages(learner_id: str) -> int:
    """Number of distinct languages the learner has saved words in."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(DISTINCT language_code) as cnt FROM words WHERE learner_id = ?",
            (learner_id,),
        ).fetchone()
        return row["cnt"]


# ── Achievements ──

def unlock_achievement(learner_id: str, badge_code: str) -> bool:
    """Unlock a badge. Returns True if newly unlocked, False if already had it."""
    now = time.time()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM achievements WHERE learner_id = ? AND badge_code = ?",
            (learner_id, badge_code),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO achievements (learner_id, badge_code, unlocked_at) VALUES (?, ?, ?)",
            (learner_id, badge_code, now),
        )
        return True


def get_achievements(learner_id: str) -> list[dict]:
    """Get all unlocked badges."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM achievements WHERE learner_id = ? ORDER BY unlocked_at DESC",
            (learner_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Daily Quests ──

def get_daily_quests(learner_id: str, date_str: str) -> list[dict]:
    """Get quests for a given date."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_quests WHERE learner_id = ? AND date = ?",
            (learner_id, date_str),
        ).fetchall()
        return [dict(r) for r in rows]


def set_daily_quests(learner_id: str, date_str: str, quests: list[dict]):
    """Insert daily quests. Each quest is {quest_code, target}."""
    with get_conn() as conn:
        for q in quests:
            conn.execute(
                """INSERT OR IGNORE INTO daily_quests
                   (learner_id, date, quest_code, target) VALUES (?, ?, ?, ?)""",
                (learner_id, date_str, q["quest_code"], q["target"]),
            )


def increment_quest(learner_id: str, date_str: str, quest_code: str, amount: int = 1):
    """Increment progress on a quest, mark completed if target reached."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE daily_quests SET progress = progress + ?
               WHERE learner_id = ? AND date = ? AND quest_code = ?""",
            (amount, learner_id, date_str, quest_code),
        )
        conn.execute(
            """UPDATE daily_quests SET completed = 1
               WHERE learner_id = ? AND date = ? AND quest_code = ?
                 AND progress >= target""",
            (learner_id, date_str, quest_code),
        )

