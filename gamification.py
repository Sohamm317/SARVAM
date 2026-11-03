"""Gamification engine: XP, levels, streaks, quests, badges.

All functions are pure or only depend on db.py, making them easy to unit-test.
"""

import math
import random
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import db

# ═══════════════════════════════════════════════════════════════════
# CONFIG  –  all tunable in one place
# ═══════════════════════════════════════════════════════════════════

XP_RULES = {
    "chat":          2,    # per coach reply
    "chat_cap":      20,   # max XP from chat per day
    "hear_word":     1,    # once per word per day
    "save_word":     5,
    "review_correct": 3,
    "review_session": 10,  # bonus for finishing a review session
    "enroll_voice":  20,   # one-time
    "daily_goal":    10,   # bonus when goal met
}

# cumulative XP to reach level L: 50 * L * (L-1)
# L2 = 100, L3 = 300, L4 = 600, L5 = 1000, ...
def xp_for_level(level: int) -> int:
    """Cumulative XP required to reach a given level."""
    return 50 * level * (level - 1)


def level_from_xp(total_xp: int) -> int:
    """Compute level from total XP."""
    # Solve 50*L*(L-1) <= total_xp  →  L = floor((1+sqrt(1+total_xp/12.5))/2)
    lvl = int((1 + math.sqrt(1 + total_xp / 12.5)) / 2)
    while xp_for_level(lvl + 1) <= total_xp:
        lvl += 1
    return max(lvl, 1)


MAX_FREEZES = 2


# ═══════════════════════════════════════════════════════════════════
# STREAKS
# ═══════════════════════════════════════════════════════════════════

def today_str(tz_name: str = "Asia/Kolkata") -> str:
    """Return today's date string in the learner's timezone."""
    return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")


def yesterday_str(tz_name: str = "Asia/Kolkata") -> str:
    """Return yesterday's date string in the learner's timezone."""
    d = datetime.now(ZoneInfo(tz_name)) - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def evaluate_streak(learner: dict) -> dict:
    """
    Called after XP is added. Checks if the daily goal was met and
    updates streak accordingly.

    Returns a dict of changes applied (for the front-end to animate).
    """
    tz = learner.get("timezone", "Asia/Kolkata")
    today = today_str(tz)
    daily = db.get_daily_progress(learner["id"], today)
    goal = learner.get("daily_goal", 20)
    changes = {"streak_grew": False, "streak_lost": False, "freeze_used": False, "goal_met_today": False}

    if daily["xp"] >= goal and not daily["goal_met"]:
        # Goal met for the first time today
        db.mark_goal_met(learner["id"], today)
        changes["goal_met_today"] = True

        last = learner.get("last_goal_date")
        yest = yesterday_str(tz)

        if last == yest or last == today:
            # Continuing or already counted today
            if last != today:
                new_streak = learner["streak_current"] + 1
                longest = max(learner["streak_longest"], new_streak)
                db.update_learner(
                    learner["id"],
                    streak_current=new_streak,
                    streak_longest=longest,
                    last_goal_date=today,
                )
                changes["streak_grew"] = True
        elif last is None:
            # First ever goal
            db.update_learner(
                learner["id"],
                streak_current=1,
                streak_longest=max(learner["streak_longest"], 1),
                last_goal_date=today,
            )
            changes["streak_grew"] = True
        else:
            # Missed at least one day
            freezes = learner.get("streak_freezes", 0)
            if freezes > 0:
                # Use a freeze
                db.update_learner(
                    learner["id"],
                    streak_freezes=freezes - 1,
                    streak_current=learner["streak_current"] + 1,
                    streak_longest=max(
                        learner["streak_longest"],
                        learner["streak_current"] + 1,
                    ),
                    last_goal_date=today,
                )
                changes["freeze_used"] = True
                changes["streak_grew"] = True
            else:
                # Streak resets
                db.update_learner(
                    learner["id"],
                    streak_current=1,
                    last_goal_date=today,
                )
                changes["streak_lost"] = True
                changes["streak_grew"] = True

    return changes


# ═══════════════════════════════════════════════════════════════════
# XP AWARDING (with de-dup and caps)
# ═══════════════════════════════════════════════════════════════════

def award_xp(learner_id: str, kind: str, tz: str = "Asia/Kolkata",
             word_id: int | None = None) -> dict:
    """
    Award XP for an action. Applies daily caps and de-duplication.

    Returns {xp_gained, total_xp, level, level_up, new_level, streak_changes}.
    """
    today = today_str(tz)
    learner = db.ensure_learner(learner_id)
    daily = db.get_daily_progress(learner_id, today)
    amount = XP_RULES.get(kind, 0)
    result = {
        "xp_gained": 0,
        "total_xp": learner["xp"],
        "level": learner["level"],
        "level_up": False,
        "new_level": learner["level"],
    }

    if amount == 0:
        return result

    # Daily caps
    if kind == "chat":
        chat_today = daily.get("xp", 0)
        if chat_today >= XP_RULES["chat_cap"]:
            return result

    # Award
    db.add_xp_event(learner_id, kind, amount)
    db.increment_daily(learner_id, today, xp=amount)

    result["xp_gained"] = amount
    result["total_xp"] = learner["xp"] + amount

    # Level check
    old_level = learner["level"]
    new_level = level_from_xp(result["total_xp"])
    if new_level > old_level:
        # Earn a streak freeze on level up (max MAX_FREEZES)
        freezes = min(learner.get("streak_freezes", 0) + 1, MAX_FREEZES)
        db.update_learner(learner_id, level=new_level, streak_freezes=freezes)
        result["level_up"] = True
        result["new_level"] = new_level
    else:
        db.update_learner(learner_id, level=new_level)

    result["level"] = new_level

    # Streak evaluation
    learner = db.get_learner(learner_id)
    streak_changes = evaluate_streak(learner)
    result["streak_changes"] = streak_changes

    # Goal bonus
    if streak_changes.get("goal_met_today"):
        db.add_xp_event(learner_id, "daily_goal", XP_RULES["daily_goal"])
        db.increment_daily(learner_id, today, xp=XP_RULES["daily_goal"])
        result["xp_gained"] += XP_RULES["daily_goal"]
        result["total_xp"] += XP_RULES["daily_goal"]

    return result


# ═══════════════════════════════════════════════════════════════════
# DAILY QUESTS
# ═══════════════════════════════════════════════════════════════════

QUEST_POOL = [
    {"quest_code": "learn_words",   "label": "Learn {n} new words",     "target_range": (3, 5)},
    {"quest_code": "hear_words",    "label": "Hear {n} words",          "target_range": (3, 7)},
    {"quest_code": "review_words",  "label": "Review {n} words",        "target_range": (5, 10)},
    {"quest_code": "chat_messages", "label": "Send {n} chat messages",  "target_range": (3, 5)},
    {"quest_code": "save_words",    "label": "Save {n} words",          "target_range": (2, 4)},
]

QUEST_LABELS = {q["quest_code"]: q["label"] for q in QUEST_POOL}


def get_or_create_quests(learner_id: str, date_str: str) -> list[dict]:
    """Get today's quests, generating 3 if none exist."""
    existing = db.get_daily_quests(learner_id, date_str)
    if existing:
        return _format_quests(existing)

    # Pick 3 random quests
    picks = random.sample(QUEST_POOL, min(3, len(QUEST_POOL)))
    quests = []
    for p in picks:
        target = random.randint(*p["target_range"])
        quests.append({"quest_code": p["quest_code"], "target": target})

    db.set_daily_quests(learner_id, date_str, quests)
    return _format_quests(db.get_daily_quests(learner_id, date_str))


def _format_quests(rows: list[dict]) -> list[dict]:
    """Add human-readable labels to quest rows."""
    result = []
    for r in rows:
        label_template = QUEST_LABELS.get(r["quest_code"], r["quest_code"])
        label = label_template.replace("{n}", str(r["target"]))
        result.append({
            "quest_code": r["quest_code"],
            "label": label,
            "target": r["target"],
            "progress": r["progress"],
            "completed": bool(r["completed"]),
        })
    return result


def track_quest(learner_id: str, date_str: str, quest_code: str, amount: int = 1):
    """Increment quest progress. Safe to call even if the quest doesn't exist today."""
    db.increment_quest(learner_id, date_str, quest_code, amount)


# ═══════════════════════════════════════════════════════════════════
# BADGES
# ═══════════════════════════════════════════════════════════════════

BADGES = {
    "first_word":       {"label": "First Word",         "icon": "📝", "desc": "Saved your first word"},
    "voice_pioneer":    {"label": "Voice Pioneer",       "icon": "🎙️", "desc": "Set up voice cloning"},
    "streak_7":         {"label": "Week Warrior",        "icon": "🔥", "desc": "7-day streak"},
    "streak_30":        {"label": "Monthly Master",      "icon": "💎", "desc": "30-day streak"},
    "words_10":         {"label": "Word Collector",      "icon": "📚", "desc": "Saved 10 words"},
    "words_50":         {"label": "Vocabulary Builder",  "icon": "🏗️", "desc": "Saved 50 words"},
    "words_100":        {"label": "Word Hoard",          "icon": "🏆", "desc": "Saved 100 words"},
    "polyglot":         {"label": "Polyglot",            "icon": "🌍", "desc": "Learning 3+ languages"},
    "perfect_review":   {"label": "Perfect Review",      "icon": "⭐", "desc": "All correct in a review session"},
    "level_5":          {"label": "Rising Star",         "icon": "🌟", "desc": "Reached level 5"},
    "level_10":         {"label": "Language Hero",       "icon": "🦸", "desc": "Reached level 10"},
}


def check_badges(learner_id: str) -> list[str]:
    """Check and unlock any newly earned badges. Returns list of newly unlocked badge codes."""
    learner = db.get_learner(learner_id)
    if not learner:
        return []

    newly_unlocked = []

    # Word count badges
    word_count = db.count_words(learner_id)
    if word_count >= 1:
        if db.unlock_achievement(learner_id, "first_word"):
            newly_unlocked.append("first_word")
    if word_count >= 10:
        if db.unlock_achievement(learner_id, "words_10"):
            newly_unlocked.append("words_10")
    if word_count >= 50:
        if db.unlock_achievement(learner_id, "words_50"):
            newly_unlocked.append("words_50")
    if word_count >= 100:
        if db.unlock_achievement(learner_id, "words_100"):
            newly_unlocked.append("words_100")

    # Voice
    if learner.get("voice_id"):
        if db.unlock_achievement(learner_id, "voice_pioneer"):
            newly_unlocked.append("voice_pioneer")

    # Streak badges
    streak = learner.get("streak_current", 0)
    if streak >= 7:
        if db.unlock_achievement(learner_id, "streak_7"):
            newly_unlocked.append("streak_7")
    if streak >= 30:
        if db.unlock_achievement(learner_id, "streak_30"):
            newly_unlocked.append("streak_30")

    # Polyglot
    lang_count = db.count_languages(learner_id)
    if lang_count >= 3:
        if db.unlock_achievement(learner_id, "polyglot"):
            newly_unlocked.append("polyglot")

    # Level badges
    level = learner.get("level", 1)
    if level >= 5:
        if db.unlock_achievement(learner_id, "level_5"):
            newly_unlocked.append("level_5")
    if level >= 10:
        if db.unlock_achievement(learner_id, "level_10"):
            newly_unlocked.append("level_10")

    return newly_unlocked


def format_badges(badge_codes: list[str]) -> list[dict]:
    """Turn badge codes into display-ready dicts."""
    return [
        {
            "code": code,
            "label": BADGES[code]["label"],
            "icon": BADGES[code]["icon"],
            "desc": BADGES[code]["desc"],
        }
        for code in badge_codes
        if code in BADGES
    ]


# ═══════════════════════════════════════════════════════════════════
# PROFILE HELPER
# ═══════════════════════════════════════════════════════════════════

def get_profile(learner_id: str) -> dict:
    """Build a complete profile dict for the /api/me endpoint."""
    learner = db.ensure_learner(learner_id)
    tz = learner.get("timezone", "Asia/Kolkata")
    today = today_str(tz)
    daily = db.get_daily_progress(learner_id, today)
    quests = get_or_create_quests(learner_id, today)
    badges = db.get_achievements(learner_id)

    current_level = learner["level"]
    next_level_xp = xp_for_level(current_level + 1)
    current_level_xp = xp_for_level(current_level)

    return {
        "xp": learner["xp"],
        "level": current_level,
        "xp_in_level": learner["xp"] - current_level_xp,
        "xp_for_next": next_level_xp - current_level_xp,
        "streak": learner["streak_current"],
        "streak_longest": learner["streak_longest"],
        "streak_freezes": learner["streak_freezes"],
        "daily_goal": learner["daily_goal"],
        "daily_xp": daily["xp"],
        "daily_goal_met": bool(daily["goal_met"]),
        "target_language": learner["target_language"],
        "timezone": tz,
        "voice_set": bool(learner.get("voice_id")),
        "quests": quests,
        "badges": format_badges([b["badge_code"] for b in badges]),
    }

