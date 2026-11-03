"""Thin wrapper over Sarvam AI's REST API for voice cloning, TTS and STT.

Endpoint reference (verified against api.sarvam.ai):
  TTS (stock)  : POST /text-to-speech
  TTS (cloned) : POST /text-to-speech  (same endpoint, voice_id replaces speaker)
  STT          : POST /speech-to-text
  Voice create : POST /voices          (multipart)
  Voice delete : DELETE /voices/{id}

Supports SARVAM_MOCK=1 for local development without a real key.
Serverless-ready (uses /tmp on Vercel or read-only filesystems).
"""

import base64
import hashlib
import os
import struct
from pathlib import Path

import requests

# ── Config ──────────────────────────────────────────────────────

SARVAM_BASE_URL    = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai")
SARVAM_CLONE_KEY   = os.environ.get("SARVAM_CLONE_API_KEY", "")
SARVAM_TTS_KEY     = os.environ.get("SARVAM_TTS_API_KEY", "") or SARVAM_CLONE_KEY
SARVAM_MOCK        = os.environ.get("SARVAM_MOCK", "0") == "1"
DAILY_TTS_CHAR_CAP = int(os.environ.get("DAILY_TTS_CHAR_CAP", "2000"))


def get_cache_dir() -> Path:
    """Return cache dir, falling back to /tmp on Vercel/serverless environments."""
    configured = os.environ.get("AUDIO_CACHE_DIR")
    if configured:
        p = Path(configured)
    elif os.environ.get("VERCEL"):
        p = Path("/tmp/audio_cache")
    else:
        p = Path("audio_cache")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


AUDIO_CACHE_DIR = get_cache_dir()


# Supported language codes
SUPPORTED_LANGUAGES = {
    "hi-IN": "Hindi",
    "bn-IN": "Bengali",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
    "mr-IN": "Marathi",
    "od-IN": "Odia",
    "pa-IN": "Punjabi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "gu-IN": "Gujarati",
    "en-IN": "English (Indian)",
    "as-IN": "Assamese",
}

# Default stock speaker name (valid female voice in bulbul:v3)
DEFAULT_SPEAKER = "shreya"

MAX_WORD_CHARS  = 500   # Sarvam TTS limit
MAX_REPLY_CHARS = 500


# ── Internal helpers ─────────────────────────────────────────────

def _key_headers(api_key: str = "") -> dict:
    """Return auth headers (no Content-Type — requests handles multipart)."""
    return {"api-subscription-key": api_key or SARVAM_CLONE_KEY}


def _json_headers(api_key: str = "") -> dict:
    return {
        "api-subscription-key": api_key or SARVAM_CLONE_KEY,
        "Content-Type": "application/json",
    }


# ── Cache ────────────────────────────────────────────────────────

def _cache_key(voice_tag: str, language_code: str, text: str) -> str:
    raw = f"{voice_tag}:{language_code}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(key: str) -> str | None:
    try:
        path = get_cache_dir() / f"{key}.wav"
        if path.exists():
            return base64.b64encode(path.read_bytes()).decode()
    except Exception:
        pass
    return None


def _put_cache(key: str, audio_b64: str):
    try:
        path = get_cache_dir() / f"{key}.wav"
        path.write_bytes(base64.b64decode(audio_b64))
    except Exception:
        pass


# ── Mock helpers ─────────────────────────────────────────────────

def _mock_wav_base64(text: str = "mock") -> str:
    """Return 0.5 s of silence as a valid base64 WAV (for SARVAM_MOCK mode)."""
    sample_rate = 16000
    num_samples = int(sample_rate * 0.5)
    pcm = b"\x00\x00" * num_samples
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", len(pcm),
    )
    return base64.b64encode(header + pcm).decode()


# ── Text-to-Speech ───────────────────────────────────────────────

def synthesize_stock(text: str, language_code: str,
                     speaker: str = DEFAULT_SPEAKER) -> str:
    """
    Synthesize text with a built-in Sarvam speaker (no voice clone needed).

    Sarvam TTS API:
        POST /text-to-speech
        { "inputs": ["..."], "target_language_code": "hi-IN",
          "speaker": "shreya", "model": "bulbul:v3", "enable_preprocessing": False }
    Response:
        { "audios": ["<base64 wav>"] }
    """
    text = text[:MAX_WORD_CHARS]
    key = _cache_key(f"stock_{speaker}", language_code, text)
    cached = _get_cached(key)
    if cached:
        return cached

    if SARVAM_MOCK:
        audio = _mock_wav_base64(text)
        _put_cache(key, audio)
        return audio

    url = f"{SARVAM_BASE_URL}/text-to-speech"
    payload = {
        "inputs": [text],
        "target_language_code": language_code,
        "speaker": speaker,
        "model": "bulbul:v3",
        "enable_preprocessing": False,  # False avoids auto-translating English into duplicate sentences
    }
    resp = requests.post(url, headers=_json_headers(SARVAM_TTS_KEY),
                         json=payload, timeout=30)
    if resp.status_code != 200:
        raise SarvamError(f"TTS failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    audios = result.get("audios") or []
    if not audios:
        raise SarvamError("No audio in TTS response")

    audio_b64 = audios[0]
    _put_cache(key, audio_b64)
    return audio_b64


def synthesize_cloned(voice_id: str, text: str, language_code: str) -> str:
    """
    Synthesize text using a previously enrolled clone voice.

    Same endpoint as synthesize_stock but uses voice_id instead of speaker.
    Sarvam cross-lingual cloning: voice language != target language is fine.
    """
    text = text[:MAX_WORD_CHARS]
    key = _cache_key(voice_id, language_code, text)
    cached = _get_cached(key)
    if cached:
        return cached

    if SARVAM_MOCK:
        audio = _mock_wav_base64(text)
        _put_cache(key, audio)
        return audio

    url = f"{SARVAM_BASE_URL}/text-to-speech"
    payload = {
        "inputs": [text],
        "target_language_code": language_code,
        "voice_id": voice_id,
        "model": "bulbul:v3",
        "enable_preprocessing": False,  # False avoids auto-translating English into duplicate sentences
    }
    resp = requests.post(url, headers=_json_headers(SARVAM_CLONE_KEY),
                         json=payload, timeout=30)
    if resp.status_code != 200:
        raise SarvamError(f"Cloned TTS failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    audios = result.get("audios") or []
    if not audios:
        raise SarvamError("No audio in cloned TTS response")

    audio_b64 = audios[0]
    _put_cache(key, audio_b64)
    return audio_b64


def synthesize_reply(voice_id: str | None, text: str, language_code: str,
                     speaker: str = DEFAULT_SPEAKER) -> str:
    """
    Synthesize a full coach reply (up to MAX_REPLY_CHARS).
    Uses cloned voice when available, otherwise falls back to stock.
    """
    text = text[:MAX_REPLY_CHARS]
    if voice_id:
        return synthesize_cloned(voice_id, text, language_code)
    return synthesize_stock(text, language_code, speaker)


# ── Speech-to-Text ───────────────────────────────────────────────

def transcribe_audio(audio_bytes: bytes, language_code: str = "en-IN") -> str:
    """
    Transcribe speech using Sarvam's STT API.

    Sarvam STT API:
        POST /speech-to-text  (multipart)
        file=<audio>, language_code=<code>, model=saaras:v3
    Response:
        { "transcript": "..." }
    """
    if SARVAM_MOCK:
        mock_phrases = {
            "hi-IN": "नमस्ते, आप कैसे हैं?",
            "ta-IN": "வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்?",
            "te-IN": "నమస్కారం, మీరు ఎలా ఉన్నారు?",
            "kn-IN": "ನಮಸ್ಕಾರ, ನೀವು ಹೇಗಿದ್ದೀರಿ?",
            "ml-IN": "നമസ്കാരം, സുഖമാണോ?",
            "bn-IN": "নমস্কার, আপনি কেমন আছেন?",
            "mr-IN": "नमस्कार, तुम्ही कसे आहात?",
            "gu-IN": "નમસ્તે, તમે કેમ છો?",
            "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਤੁਸੀਂ ਕਿਵੇਂ ਹੋ?",
            "en-IN": "Hello, how do you say thank you in Tamil?",
        }
        return mock_phrases.get(language_code, "Hello, how are you?")

    url = f"{SARVAM_BASE_URL}/speech-to-text"
    files = {"file": ("recording.webm", audio_bytes, "audio/webm")}
    data  = {"language_code": language_code, "model": "saaras:v3"}

    resp = requests.post(url, headers=_key_headers(), files=files,
                         data=data, timeout=60)
    if resp.status_code != 200:
        raise SarvamError(f"STT failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    transcript = result.get("transcript", "")
    if not transcript:
        raise SarvamError("Empty transcript returned by STT")
    return transcript


# ── Voice Management ─────────────────────────────────────────────

def create_voice(audio_bytes: bytes, language_code: str,
                 display_name: str = "learner") -> dict:
    """
    Enroll a new voice clone.

    Sarvam Voices API:
        POST /voices  (multipart)
        file=<audio>, language_code=<code>, name=<name>
    Response:
        { "id": "voice_xxx", ... }

    Returns: {"voice_id": str, "transcript": str}
    """
    if SARVAM_MOCK:
        mock_id = f"mock_voice_{hashlib.md5(audio_bytes[:100]).hexdigest()[:8]}"
        return {"voice_id": mock_id, "transcript": "[mock transcript]"}

    url = f"{SARVAM_BASE_URL}/voices"
    files = {"file": ("enrollment.webm", audio_bytes, "audio/webm")}
    data  = {"name": display_name, "language_code": language_code}

    resp = requests.post(url, headers=_key_headers(), files=files,
                         data=data, timeout=60)
    if resp.status_code not in (200, 201):
        raise SarvamError(f"Voice creation failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    voice_id = (result.get("id") or result.get("voice_id") or "").strip()
    if not voice_id:
        raise SarvamError(f"No voice_id in creation response: {result}")

    return {
        "voice_id": voice_id,
        "transcript": result.get("transcript", ""),
    }


def delete_voice(voice_id: str) -> bool:
    """Delete an enrolled voice. Returns True on success or if already gone."""
    if SARVAM_MOCK:
        return True

    url = f"{SARVAM_BASE_URL}/voices/{voice_id}"
    resp = requests.delete(url, headers=_key_headers(), timeout=30)
    return resp.status_code in (200, 204, 404)


# ── Validation ───────────────────────────────────────────────────

def validate_language(code: str) -> bool:
    return code in SUPPORTED_LANGUAGES


def get_supported_languages() -> dict:
    return dict(SUPPORTED_LANGUAGES)


class SarvamError(Exception):
    """Raised on any Sarvam API error."""
    pass
