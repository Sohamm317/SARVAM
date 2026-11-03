"""Thin wrapper over Sarvam AI's REST API for voice cloning and TTS.

Supports a SARVAM_MOCK=1 mode that returns silent audio, so the app
can be built and tested without a real API key.
"""

import base64
import hashlib
import os
import json
import time
from pathlib import Path

import requests

# ── Config ──

SARVAM_BASE_URL = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai")
SARVAM_CLONE_API_KEY = os.environ.get("SARVAM_CLONE_API_KEY", "")
SARVAM_TTS_API_KEY = os.environ.get("SARVAM_TTS_API_KEY", "") or SARVAM_CLONE_API_KEY
SARVAM_MOCK = os.environ.get("SARVAM_MOCK", "0") == "1"
DAILY_TTS_CHAR_CAP = int(os.environ.get("DAILY_TTS_CHAR_CAP", "2000"))

AUDIO_CACHE_DIR = Path(os.environ.get("AUDIO_CACHE_DIR", "audio_cache"))
AUDIO_CACHE_DIR.mkdir(exist_ok=True)

# Supported languages for voice cloning
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

MAX_WORD_CHARS = 100  # max chars per word/phrase for TTS


def _headers(api_key: str = None) -> dict:
    key = api_key or SARVAM_CLONE_API_KEY
    return {
        "api-subscription-key": key,
        "Content-Type": "application/json",
    }


def _upload_headers(api_key: str = None) -> dict:
    key = api_key or SARVAM_CLONE_API_KEY
    return {
        "api-subscription-key": key,
    }


# ── Mock helpers ──

def _mock_wav_base64(text: str = "mock") -> str:
    """Generate a tiny valid WAV file (silence) as base64."""
    # 0.5s of silence at 16kHz, 16-bit mono
    import struct
    sample_rate = 16000
    duration = 0.5
    num_samples = int(sample_rate * duration)
    data = b"\x00\x00" * num_samples
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,   # chunk size
        1,    # PCM
        1,    # mono
        sample_rate,
        sample_rate * 2,  # byte rate
        2,    # block align
        16,   # bits per sample
        b"data",
        len(data),
    )
    return base64.b64encode(header + data).decode()


# ── Cache ──

def _cache_key(voice_id: str, language_code: str, text: str) -> str:
    raw = f"{voice_id}:{language_code}:{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(key: str) -> str | None:
    path = AUDIO_CACHE_DIR / f"{key}.wav"
    if path.exists():
        return base64.b64encode(path.read_bytes()).decode()
    return None


def _put_cache(key: str, audio_b64: str):
    path = AUDIO_CACHE_DIR / f"{key}.wav"
    path.write_bytes(base64.b64decode(audio_b64))


# ── Voice Management ──

def create_voice(audio_bytes: bytes, language_code: str, display_name: str = "learner") -> dict:
    """
    Create a saved voice from an audio clip.

    Returns: {"voice_id": str, "transcript": str}
    Raises: SarvamError on failure.
    """
    if SARVAM_MOCK:
        mock_id = f"mock_voice_{hashlib.md5(audio_bytes[:100]).hexdigest()[:8]}"
        return {"voice_id": mock_id, "transcript": "[mock transcript]"}

    url = f"{SARVAM_BASE_URL}/text-to-speech/voices/create"

    files = {
        "reference_audio": ("enrollment.wav", audio_bytes, "audio/wav"),
    }
    data = {
        "name": display_name,
        "reference_audio_language_code": language_code,
    }

    resp = requests.post(url, headers=_upload_headers(), files=files, data=data, timeout=60)
    if resp.status_code != 200:
        raise SarvamError(f"Voice creation failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    return {
        "voice_id": result.get("id") or result.get("voice_id"),
        "transcript": result.get("transcript", ""),
    }


def delete_voice(voice_id: str) -> bool:
    """Delete a saved voice. Returns True on success."""
    if SARVAM_MOCK:
        return True

    url = f"{SARVAM_BASE_URL}/text-to-speech/voices/delete/{voice_id}"
    resp = requests.delete(url, headers=_headers(), timeout=30)
    return resp.status_code in (200, 204, 404)


def synthesize_cloned(voice_id: str, text: str, language_code: str) -> str:
    """
    Synthesize speech using a cloned voice.

    Returns base64-encoded WAV audio.
    Raises: SarvamError on failure.
    """
    # Check cache first
    key = _cache_key(voice_id, language_code, text)
    cached = _get_cached(key)
    if cached:
        return cached

    if SARVAM_MOCK:
        audio = _mock_wav_base64(text)
        _put_cache(key, audio)
        return audio

    url = f"{SARVAM_BASE_URL}/text-to-speech/generate"
    payload = {
        "target_language_code": language_code,
        "text": text[:MAX_WORD_CHARS],
        "voice_id": voice_id,
        "model": "bulbul:v2",
    }

    resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
    if resp.status_code != 200:
        raise SarvamError(f"TTS failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    audio_b64 = result.get("audio") or result.get("audio_base64", "")
    if not audio_b64:
        raise SarvamError("No audio in TTS response")

    _put_cache(key, audio_b64)
    return audio_b64


def synthesize_stock(text: str, language_code: str, speaker: str = "meera") -> str:
    """
    Synthesize speech using a stock (non-cloned) voice for comparison.

    Returns base64-encoded WAV audio.
    """
    key = _cache_key(f"stock_{speaker}", language_code, text)
    cached = _get_cached(key)
    if cached:
        return cached

    if SARVAM_MOCK:
        audio = _mock_wav_base64(text)
        _put_cache(key, audio)
        return audio

    url = f"{SARVAM_BASE_URL}/text-to-speech/generate"
    payload = {
        "target_language_code": language_code,
        "text": text[:MAX_WORD_CHARS],
        "speaker": speaker,
        "model": "bulbul:v2",
    }

    resp = requests.post(url, headers=_headers(SARVAM_TTS_API_KEY), json=payload, timeout=30)
    if resp.status_code != 200:
        raise SarvamError(f"Stock TTS failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    audio_b64 = result.get("audio") or result.get("audio_base64", "")
    if audio_b64:
        _put_cache(key, audio_b64)
    return audio_b64


def validate_language(code: str) -> bool:
    """Check if a language code is supported."""
    return code in SUPPORTED_LANGUAGES


def get_supported_languages() -> dict:
    """Return the supported language map."""
    return dict(SUPPORTED_LANGUAGES)


class SarvamError(Exception):
    """Custom exception for Sarvam API errors."""
    pass

