"""Unit tests for the gamification engine."""

import os
import sys
import tempfile
import time

# Use a temp database for testing
_test_db = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_PATH"] = _test_db

import db
import gamification


def setup():
    """Initialize a fresh test database."""
    db.init_db()


def teardown():
    """Remove the test database."""
    if os.path.exists(_test_db):
        os.unlink(_test_db)


def test_xp_for_level():
    print("── XP for Level ──")
    assert gamification.xp_for_level(1) == 0
    assert gamification.xp_for_level(2) == 100
    assert gamification.xp_for_level(3) == 300
    assert gamification.xp_for_level(4) == 600
    assert gamification.xp_for_level(5) == 1000
    print("  ✓ OK\n")


def test_level_from_xp():
    print("── Level from XP ──")
    assert gamification.level_from_xp(0) == 1
    assert gamification.level_from_xp(50) == 1
    assert gamification.level_from_xp(99) == 1
    assert gamification.level_from_xp(100) == 2
    assert gamification.level_from_xp(299) == 2
    assert gamification.level_from_xp(300) == 3
    assert gamification.level_from_xp(999) == 4
    assert gamification.level_from_xp(1000) == 5
    print("  ✓ OK\n")


def test_ensure_learner():
    print("── Ensure Learner ──")
    learner = db.ensure_learner("test_learner_1")
    assert learner["id"] == "test_learner_1"
    assert learner["xp"] == 0
    assert learner["level"] == 1
    assert learner["streak_current"] == 0

    # Should return same learner
    learner2 = db.ensure_learner("test_learner_1")
    assert learner2["id"] == learner["id"]
    print("  ✓ OK\n")


def test_award_xp():
    print("── Award XP ──")
    lid = "test_xp_learner"
    db.ensure_learner(lid)

    result = gamification.award_xp(lid, "save_word")
    assert result["xp_gained"] >= 5, f"Expected >= 5 XP, got {result['xp_gained']}"
    assert result["total_xp"] >= 5
    print(f"  After save_word: {result['total_xp']} XP")

    result2 = gamification.award_xp(lid, "chat")
    assert result2["xp_gained"] >= 2
    print(f"  After chat: {result2['total_xp']} XP")
    print("  ✓ OK\n")


def test_chat_cap():
    print("── Chat XP Cap ──")
    lid = "test_cap_learner"
    db.ensure_learner(lid)

    total_gained = 0
    for i in range(15):
        result = gamification.award_xp(lid, "chat")
        total_gained += result["xp_gained"]

    # Chat cap is 20, each chat gives 2, so max 10 chats = 20 XP from chat
    assert total_gained <= gamification.XP_RULES["chat_cap"] + gamification.XP_RULES["daily_goal"], \
        f"Chat XP exceeded cap: {total_gained}"
    print(f"  Total chat XP after 15 attempts: {total_gained}")
    print("  ✓ OK\n")


def test_level_up():
    print("── Level Up ──")
    lid = "test_level_learner"
    db.ensure_learner(lid)

    # Give enough XP to reach level 2 (100 XP)
    for i in range(20):
        db.add_xp_event(lid, "test", 5)
    db.update_learner(lid, xp=100)

    learner = db.get_learner(lid)
    level = gamification.level_from_xp(learner["xp"])
    assert level == 2, f"Expected level 2 at 100 XP, got {level}"
    print(f"  At 100 XP: level {level}")
    print("  ✓ OK\n")


def test_save_and_get_words():
    print("── Save and Get Words ──")
    lid = "test_words_learner"
    db.ensure_learner(lid)

    word = db.save_word(lid, "hi-IN", "नमस्ते", "namaste", "hello")
    assert word["text"] == "नमस्ते"
    assert word["meaning"] == "hello"

    words = db.get_words(lid)
    assert len(words) == 1

    words_hi = db.get_words(lid, "hi-IN")
    assert len(words_hi) == 1

    words_ta = db.get_words(lid, "ta-IN")
    assert len(words_ta) == 0

    # Upsert: same word should update, not duplicate
    word2 = db.save_word(lid, "hi-IN", "नमस्ते", "namaste", "greetings")
    words = db.get_words(lid)
    assert len(words) == 1
    assert words[0]["meaning"] == "greetings"
    print("  ✓ OK\n")


def test_word_review():
    print("── Word Review ──")
    lid = "test_review_learner"
    db.ensure_learner(lid)

    db.save_word(lid, "hi-IN", "धन्यवाद", "dhanyavaad", "thank you")
    words = db.get_words_for_review(lid, "2025-01-01")
    assert len(words) >= 1

    word = words[0]
    assert word["leitner_box"] == 0

    db.update_word_review(word["id"], True, "2025-01-03")
    updated = db.get_words(lid, "hi-IN")
    w = [w for w in updated if w["id"] == word["id"]][0]
    assert w["leitner_box"] == 1
    print("  ✓ OK\n")


def test_badges():
    print("── Badges ──")
    lid = "test_badge_learner"
    db.ensure_learner(lid)
    db.save_word(lid, "hi-IN", "test", "test", "test")

    newly = gamification.check_badges(lid)
    assert "first_word" in newly, f"Expected first_word badge, got {newly}"
    print(f"  Unlocked: {newly}")

    # Should not unlock again
    newly2 = gamification.check_badges(lid)
    assert "first_word" not in newly2
    print("  ✓ No duplicate badges\n")


def test_quests():
    print("── Daily Quests ──")
    lid = "test_quest_learner"
    db.ensure_learner(lid)

    quests = gamification.get_or_create_quests(lid, "2025-01-01")
    assert len(quests) == 3
    print(f"  Quests: {[q['label'] for q in quests]}")

    # Should return same quests on second call
    quests2 = gamification.get_or_create_quests(lid, "2025-01-01")
    assert len(quests2) == 3
    assert quests[0]["quest_code"] == quests2[0]["quest_code"]
    print("  ✓ OK\n")


def test_daily_progress():
    print("── Daily Progress ──")
    lid = "test_progress_learner"
    db.ensure_learner(lid)

    prog = db.get_daily_progress(lid, "2025-01-01")
    assert prog["xp"] == 0

    db.increment_daily(lid, "2025-01-01", xp=10, words_learned=2)
    prog = db.get_daily_progress(lid, "2025-01-01")
    assert prog["xp"] == 10
    assert prog["words_learned"] == 2
    print("  ✓ OK\n")


def test_profile():
    print("── Profile ──")
    lid = "test_profile_learner"
    db.ensure_learner(lid)

    profile = gamification.get_profile(lid)
    assert profile["level"] == 1
    assert profile["xp"] == 0
    assert "quests" in profile
    assert "badges" in profile
    print(f"  Profile: level={profile['level']}, xp={profile['xp']}")
    print("  ✓ OK\n")


if __name__ == "__main__":
    print("=" * 50)
    print("Gamification Unit Tests")
    print("=" * 50)
    print()

    setup()

    tests = [
        test_xp_for_level,
        test_level_from_xp,
        test_ensure_learner,
        test_award_xp,
        test_chat_cap,
        test_level_up,
        test_save_and_get_words,
        test_word_review,
        test_badges,
        test_quests,
        test_daily_progress,
        test_profile,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  ✗ FAILED: {e}")
            traceback.print_exc()
            print()
            failed += 1

    teardown()

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    sys.exit(1 if failed else 0)

