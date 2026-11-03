import os
os.environ.setdefault('SARVAM_MOCK', '1')
os.environ.setdefault('DATABASE_PATH', 'test_smoke.db')

import db; print('db OK')
import coach; print('coach OK')
import gamification; print('gamification OK')
import sarvam_client; print('sarvam_client OK')

db.init_db(); print('DB init OK')

# Coach JSON parse
raw = '{"reply": "Hello!", "vocab": [{"text": "namaste", "romanized": "namaste", "meaning": "hello", "language_code": "hi-IN"}]}'
r = coach.parse_coach_response(raw)
assert r['reply'] == 'Hello!' and len(r['vocab']) == 1, f"coach parse failed: {r}"
print('coach parse OK')

# Plain text fallback
r2 = coach.parse_coach_response('Just a plain reply')
assert r2['reply'] == 'Just a plain reply' and r2['vocab'] == []
print('coach fallback OK')

# Profile
lid = 'smoke_test_user'
profile = gamification.get_profile(lid)
assert profile['level'] == 1 and profile['xp'] == 0
print('profile OK')

# Award XP
xp = gamification.award_xp(lid, 'save_word')
assert xp['xp_gained'] >= 5, f"expected >=5, got {xp['xp_gained']}"
print('award_xp OK (+%d XP)' % xp['xp_gained'])

# Save word
w = db.save_word(lid, 'hi-IN', 'namaste', 'namaste', 'hello')
assert w['text'] == 'namaste'
print('save_word DB OK')

# Badges
badges = gamification.check_badges(lid)
assert 'first_word' in badges, f"expected first_word in {badges}"
print('badges OK: %s' % badges)

# Mock voice
result = sarvam_client.create_voice(b'fake audio data that is long enough for the hash', 'en-IN')
assert result['voice_id'].startswith('mock_')
print('mock voice OK: %s' % result['voice_id'])

# Mock TTS
audio = sarvam_client.synthesize_cloned(result['voice_id'], 'hello world', 'hi-IN')
assert len(audio) > 100
print('mock TTS OK (%d chars)' % len(audio))

# Stock TTS
audio2 = sarvam_client.synthesize_stock('hello', 'en-IN')
assert len(audio2) > 100
print('mock stock TTS OK')

# Quest generation
today = gamification.today_str()
quests = gamification.get_or_create_quests(lid, today)
assert len(quests) == 3
print('quests OK: %d quests for today' % len(quests))

# Cleanup
if os.path.exists('test_smoke.db'):
    os.unlink('test_smoke.db')
# Clean up audio_cache mock files
import glob, pathlib
for f in glob.glob('audio_cache/mock_*.wav'):
    try: os.unlink(f)
    except: pass

print()
print('All smoke tests passed.')

