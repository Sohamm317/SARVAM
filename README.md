# Language Coach with Voice Cloning

A Flask-based language learning chatbot that clones your voice to generate correct pronunciation for Indian language vocabulary. Built on top of the Persona Chat app, it adds a language coach mode, gamification (XP, levels, streaks, quests, badges), voice cloning via Sarvam AI, and spaced-repetition review.

## Features

### Language Coach Mode
- AI-powered language coach for 12 Indian languages
- Vocabulary cards with native script, romanization, and meaning
- "Hear in my voice" — pronunciation generated in your cloned voice
- Word bank to save and organize vocabulary

### Voice Cloning (Sarvam AI)
- Record 10–15 seconds of your voice to create a voice clone
- Cross-lingual synthesis: hear yourself speak any supported language
- Audio caching to minimize API calls
- Consent-based enrollment with delete capability

### Gamification (Duolingo-style)
- **XP system**: earn XP for chatting, learning words, reviews, and voice setup
- **Levels**: progress through levels with increasing XP requirements
- **Daily streaks**: maintain streaks by meeting your daily XP goal
- **Streak freezes**: earned at level-ups, automatically used on missed days
- **Daily quests**: 3 random quests each day
- **Badges**: 11 achievements (First Word, Voice Pioneer, 7/30-day streaks, etc.)
- **Spaced repetition**: Leitner-box review system with multiple-choice exercises

### Persona Chat (V1, preserved)
- Custom persona via text description
- Quick-start persona presets
- Multi-turn memory with history trimming

## Supported Languages

Hindi, Bengali, Kannada, Malayalam, Marathi, Odia, Punjabi, Tamil, Telugu, Gujarati, English (Indian), Assamese

## Project Structure

```
SARVAM/
├── app.py                  # Flask routes (persona + coach + voice + review)
├── db.py                   # SQLite database setup and queries
├── coach.py                # Coach system prompt and JSON response parsing
├── gamification.py         # XP, levels, streaks, quests, badges engine
├── sarvam_client.py        # Sarvam AI API wrapper (voice cloning + TTS)
├── test_api.py             # Standalone LLM API sanity check
├── test_sarvam.py          # Standalone Sarvam API test suite
├── tests/
│   └── test_gamification.py # Unit tests for gamification logic
├── templates/
│   └── index.html          # Single-page UI
├── .env                    # Secrets (not committed)
├── .gitignore
└── README.md
```

## Requirements

- Python 3.9 or newer
- An API key from an OpenAI-compatible provider (e.g. Groq)
- A Sarvam AI API key with `text_to_speech_voice_cloning` capability

Python packages:

| Package | Used for |
|---|---|
| `flask` | Web server, routes, and sessions |
| `openai` | Client for OpenAI-compatible APIs |
| `python-dotenv` | Loading secrets from `.env` |
| `requests` | HTTP calls to Sarvam AI |
| `tzdata` | Timezone data (needed on Windows) |

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install flask openai python-dotenv requests tzdata
```

Create a `.env` file:

```env
FLASK_SECRET_KEY=your-random-string
LLM_API_KEY=your-provider-key
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=exact-model-id-from-your-provider

# Sarvam AI Voice Cloning
SARVAM_CLONE_API_KEY=your-sarvam-key      # needs voice-cloning capability
SARVAM_TTS_API_KEY=                        # optional, for stock voice comparison
SARVAM_BASE_URL=https://api.sarvam.ai
SARVAM_MOCK=1                              # 1 = mock mode (no real API calls)
DAILY_TTS_CHAR_CAP=2000
DATABASE_PATH=persona_chat.db
```

### Mock Mode

Set `SARVAM_MOCK=1` to develop and test without a real Sarvam API key. Voice enrollment and synthesis will return silent audio. Set to `0` when your key is ready.

## Run

Test the APIs first:

```bash
python test_api.py         # test the LLM connection
python test_sarvam.py      # test Sarvam API / mock mode
```

Run the gamification unit tests:

```bash
python tests/test_gamification.py
```

Start the app and open http://127.0.0.1:5000:

```bash
python app.py
```

## Deploying to Vercel

1. Push your code to GitHub (ensure `.env` and `*.txt` containing API keys remain uncommitted).
2. Go to [Vercel](https://vercel.com) and click **Add New Project** -> import your GitHub repository.
3. In **Project Settings** -> **Environment Variables**, add the variables from `.env.example`:
   - `FLASK_SECRET_KEY`
   - `LLM_BASE_URL`
   - `LLM_API_KEY`
   - `LLM_MODEL`
   - `SARVAM_CLONE_API_KEY`
   - `SARVAM_TTS_API_KEY`
   - `SARVAM_BASE_URL` (https://api.sarvam.ai)
   - `SARVAM_MOCK` (0 for production, 1 for mock)
4. Click **Deploy**. Vercel will install from `requirements.txt` and route requests through `api/index.py` using `vercel.json`.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Main page |
| `/persona` | POST | Set persona (persona mode) |
| `/chat` | POST | Send a message (both modes) |
| `/coach/start` | POST | Switch to language coach mode |
| `/api/me` | GET | Get learner profile |
| `/api/settings` | POST | Update target language, daily goal, timezone |
| `/voice/enroll` | POST | Enroll voice from audio recording |
| `/voice` | DELETE | Delete cloned voice |
| `/speak` | POST | Synthesize speech in cloned/stock voice |
| `/words` | GET | List saved words |
| `/words` | POST | Save a word |
| `/review/next` | GET | Get review cards |
| `/review/answer` | POST | Submit a review answer |

## Gamification Rules

| Action | XP | Notes |
|---|---|---|
| Coach message | +2 | Capped at 20/day |
| Hear a word | +1 | Once per word per day |
| Save a word | +5 | |
| Correct review | +3 | |
| Finish review session | +10 | Bonus |
| Enroll voice | +20 | One-time |
| Meet daily goal | +10 | Bonus |

**Levels**: XP needed = 50 × L × (L−1). Level 2 at 100 XP, Level 3 at 300, Level 5 at 1000.

**Streaks**: Grow when you meet your daily XP goal. Missing a day uses a streak freeze (earned at level-up, max 2). Otherwise the streak resets.

## Privacy & Consent

- Voice enrollment requires explicit consent via checkbox
- Only live microphone recordings are accepted (no file upload)
- Voice data is sent to Sarvam AI for processing and stored there until deleted
- The "Delete My Voice" button removes the voice from both Sarvam and the local database
- Audio is labelled as AI-generated model pronunciation
- No accounts — identity is via a one-year signed cookie

## Known Limitations

- Chat history is in memory; resets on server restart (profile/words/progress persist in SQLite)
- Voice cloning quality depends on the recording environment and Sarvam's beta service
- The coach's vocabulary accuracy depends on the underlying LLM model
- No phoneme-level pronunciation scoring (planned for a future version)
- Cookie-based identity: clearing cookies or switching devices loses the session
