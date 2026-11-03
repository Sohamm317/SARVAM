"""Standalone test for Sarvam API connectivity and capabilities.

Usage:
    python test_sarvam.py

Set SARVAM_MOCK=1 in .env to test without a real key.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Allow mock mode for testing
if os.environ.get("SARVAM_MOCK", "0") == "1":
    print("✓ Running in MOCK mode (no real API calls)")
    print()

import sarvam_client


def test_supported_languages():
    print("── Supported Languages ──")
    langs = sarvam_client.get_supported_languages()
    for code, name in sorted(langs.items()):
        print(f"  {code}: {name}")
    print(f"  Total: {len(langs)}")
    assert len(langs) > 0, "No languages!"
    print("  ✓ OK\n")


def test_language_validation():
    print("── Language Validation ──")
    assert sarvam_client.validate_language("hi-IN"), "hi-IN should be valid"
    assert sarvam_client.validate_language("ta-IN"), "ta-IN should be valid"
    assert not sarvam_client.validate_language("xx-XX"), "xx-XX should be invalid"
    print("  ✓ OK\n")


def test_mock_wav():
    print("── Mock WAV Generation ──")
    wav_b64 = sarvam_client._mock_wav_base64("test")
    import base64
    wav_bytes = base64.b64decode(wav_b64)
    assert wav_bytes[:4] == b"RIFF", "Not a valid WAV header"
    assert len(wav_bytes) > 44, "WAV too short"
    print(f"  Generated {len(wav_bytes)} bytes")
    print("  ✓ OK\n")


def test_cache():
    print("── Audio Cache ──")
    key = sarvam_client._cache_key("test_voice", "hi-IN", "test_text")
    print(f"  Cache key: {key[:16]}...")

    # Put and get
    mock_audio = sarvam_client._mock_wav_base64("cache_test")
    sarvam_client._put_cache(key, mock_audio)
    retrieved = sarvam_client._get_cached(key)
    assert retrieved == mock_audio, "Cache mismatch!"
    print("  ✓ OK\n")

    # Clean up test cache
    cache_path = sarvam_client.AUDIO_CACHE_DIR / f"{key}.wav"
    if cache_path.exists():
        cache_path.unlink()


def test_voice_creation_mock():
    """Only runs in mock mode."""
    if not sarvam_client.SARVAM_MOCK:
        print("── Voice Creation (skipped: not in mock mode) ──\n")
        return

    print("── Voice Creation (mock) ──")
    result = sarvam_client.create_voice(b"fake_audio_data", "en-IN", "test_learner")
    assert "voice_id" in result, "No voice_id returned"
    assert result["voice_id"].startswith("mock_"), "Expected mock voice ID"
    print(f"  Voice ID: {result['voice_id']}")
    print(f"  Transcript: {result['transcript']}")
    print("  ✓ OK\n")


def test_synthesis_mock():
    """Only runs in mock mode."""
    if not sarvam_client.SARVAM_MOCK:
        print("── Synthesis (skipped: not in mock mode) ──\n")
        return

    print("── Synthesis (mock) ──")
    audio = sarvam_client.synthesize_cloned("mock_voice_123", "नमस्ते", "hi-IN")
    assert len(audio) > 0, "No audio returned"
    import base64
    wav = base64.b64decode(audio)
    assert wav[:4] == b"RIFF", "Not valid WAV"
    print(f"  Audio: {len(wav)} bytes")
    print("  ✓ OK\n")


def test_stock_synthesis_mock():
    if not sarvam_client.SARVAM_MOCK:
        print("── Stock TTS (skipped: not in mock mode) ──\n")
        return

    print("── Stock TTS (mock) ──")
    audio = sarvam_client.synthesize_stock("hello", "en-IN")
    assert len(audio) > 0, "No audio"
    print("  ✓ OK\n")


def test_transcription_mock():
    if not sarvam_client.SARVAM_MOCK:
        print("── Transcription (skipped: not in mock mode) ──\n")
        return

    print("── Transcription (mock) ──")
    import os
    fake_audio = b"\x00" * 5000   # fake audio bytes
    transcript = sarvam_client.transcribe_audio(fake_audio, "en-IN")
    assert isinstance(transcript, str) and len(transcript) > 0, "Empty transcript"
    print("  Transcript:", transcript)
    print("  ✓ OK\n")

    # Each target language should return something
    for code in ["hi-IN", "ta-IN", "te-IN"]:
        t = sarvam_client.transcribe_audio(fake_audio, code)
        assert t, f"Empty transcript for {code}"
    print("  ✓ Multi-language mock OK\n")


def test_synthesize_reply_mock():
    if not sarvam_client.SARVAM_MOCK:
        print("── Synthesize Reply (skipped) ──\n")
        return

    print("── Synthesize Reply (mock) ──")
    # With cloned voice
    audio = sarvam_client.synthesize_reply("mock_voice_123", "Hello there!", "en-IN")
    assert len(audio) > 100
    # Without cloned voice (stock fallback)
    audio2 = sarvam_client.synthesize_reply(None, "Hello there!", "en-IN")
    assert len(audio2) > 100
    print("  ✓ OK\n")


if __name__ == "__main__":
    print("=" * 50)
    print("Sarvam API Test Suite")
    print("=" * 50)
    print()

    tests = [
        test_supported_languages,
        test_language_validation,
        test_mock_wav,
        test_cache,
        test_voice_creation_mock,
        test_synthesis_mock,
        test_stock_synthesis_mock,
        test_transcription_mock,
        test_synthesize_reply_mock,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}\n")
            failed += 1

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    import sys
    sys.exit(1 if failed else 0)

