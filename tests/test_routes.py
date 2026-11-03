"""Flask route integration test. Spins up the server, hits all routes, then exits."""
import os, sys, time, json, threading, subprocess, urllib.request, urllib.error

os.environ.setdefault("SARVAM_MOCK", "1")
os.environ.setdefault("DATABASE_PATH", "test_routes.db")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-12345")
os.environ.setdefault("LLM_API_KEY", "fake")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:9999/v1")
os.environ.setdefault("LLM_MODEL", "test-model")

BASE = "http://127.0.0.1:5000"
cookie_jar = {}
errors = []


def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if data:
        r.add_header("Content-Type", "application/json")
    if cookie_jar:
        r.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookie_jar.items()))
    try:
        with urllib.request.urlopen(r) as resp:
            for c in (resp.headers.get_all("Set-Cookie") or []):
                parts = c.split(";")[0].split("=", 1)
                if len(parts) == 2:
                    cookie_jar[parts[0].strip()] = parts[1].strip()
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", errors="replace")}


def req_multipart(path, fields, files):
    """POST multipart/form-data. files = {name: (filename, bytes, mime)}"""
    boundary = "----TestBoundary1234"
    body_parts = []
    for name, value in fields.items():
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}".encode()
        )
    for name, (filename, data, mime) in files.items():
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode() + data
        )
    body = b"\r\n".join(body_parts) + f"\r\n--{boundary}--\r\n".encode()
    url = BASE + path
    r = urllib.request.Request(url, data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if cookie_jar:
        r.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookie_jar.items()))
    try:
        with urllib.request.urlopen(r) as resp:
            for c in (resp.headers.get_all("Set-Cookie") or []):
                parts = c.split(";")[0].split("=", 1)
                if len(parts) == 2:
                    cookie_jar[parts[0].strip()] = parts[1].strip()
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", errors="replace")}


def check(label, cond, detail=""):
    if cond:
        print("  PASS", label)
    else:
        print("  FAIL", label, detail)
        errors.append(label)


# Start server
server = subprocess.Popen(
    [sys.executable, "app.py"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env=os.environ.copy(),
)
time.sleep(2.5)

try:
    print("=== Route Tests ===")

    # GET /
    with urllib.request.urlopen(BASE + "/") as r:
        check("GET /", r.status == 200)

    # GET /api/me
    s, d = req("GET", "/api/me")
    check("GET /api/me", s == 200 and "level" in d and "streak" in d,
          f"status={s}, keys={list(d.keys())}")

    # POST /api/settings
    s, d = req("POST", "/api/settings", {"target_language": "ta-IN", "daily_goal": 10})
    check("POST /api/settings", s == 200 and d.get("ok"), str(d))

    # POST /coach/start
    s, d = req("POST", "/coach/start", {})
    check("POST /coach/start", s == 200 and d.get("ok"), str(d))

    # GET /words empty
    s, d = req("GET", "/words")
    check("GET /words (empty)", s == 200 and isinstance(d.get("words"), list), str(d))

    # POST /words
    s, d = req("POST", "/words", {"text": "vanakkam", "meaning": "hello", "language_code": "ta-IN", "romanized": "vanakkam"})
    check("POST /words", s == 200 and d.get("ok"), str(d))
    xp_from_word = d.get("xp_gained", 0)
    print("    xp_gained:", xp_from_word)

    # GET /words (1 word)
    s, d = req("GET", "/words")
    check("GET /words (1 word)", s == 200 and len(d.get("words", [])) >= 1, str(d))

    # POST /speak with no voice enrolled
    s, d = req("POST", "/speak", {"text": "hello", "language_code": "ta-IN"})
    check("POST /speak (no voice -> 400)", s == 400, str(d))

    # POST /speak stock voice
    s, d = req("POST", "/speak", {"text": "hello", "language_code": "en-IN", "stock": True})
    check("POST /speak stock", s == 200 and len(d.get("audio", "")) > 100, str(d)[:80])

    # POST /speak reply mode (no voice — falls back to stock)
    s, d = req("POST", "/speak", {"text": "Great question! Let me explain.", "language_code": "en-IN", "mode": "reply"})
    check("POST /speak reply mode", s == 200 and len(d.get("audio", "")) > 100, str(d)[:80])

    # POST /transcribe  — bad/fake bytes → Sarvam returns 400; our route surfaces it as 502
    # (In real use the browser sends actual recorded webm; fake bytes are intentionally invalid)
    fake_webm = b"\x1aE\xdf\xa3" + b"\x00" * 500   # fake webm header + padding
    s, d = req_multipart("/transcribe", {"language": "en-IN"}, {"audio": ("input.webm", fake_webm, "audio/webm")})
    # Either 200 (some providers accept any bytes) or 502 (Sarvam rejected invalid audio) — not a 500
    check("POST /transcribe (route reachable)", s in (200, 400, 502), str(d)[:120])

    # GET /review/next (only 1 word - expect 400)
    s, d = req("GET", "/review/next")
    check("GET /review/next (too few -> 400)", s == 400, str(d))

    # Add 3 more words
    for w in [("nandri", "ta-IN", "thank you"), ("saapida", "ta-IN", "to eat"), ("thanneer", "ta-IN", "water")]:
        req("POST", "/words", {"text": w[0], "meaning": w[2], "language_code": w[1], "romanized": w[0]})

    # GET /review/next (4 words now - expect 200)
    s, d = req("GET", "/review/next")
    check("GET /review/next (4 words)", s == 200 and len(d.get("cards", [])) >= 1, str(d)[:100])

    if s == 200 and d.get("cards"):
        card = d["cards"][0]
        # POST /review/answer correct
        s2, d2 = req("POST", "/review/answer", {
            "word_id": card["word_id"],
            "answer": card["correct_meaning"],
            "is_last": False,
            "session_correct": 1,
            "session_total": 4,
        })
        check("POST /review/answer correct", s2 == 200 and d2.get("correct") is True, str(d2))

        # POST /review/answer wrong
        s3, d3 = req("POST", "/review/answer", {
            "word_id": card["word_id"],
            "answer": "wrong__answer",
            "is_last": True,
            "session_correct": 1,
            "session_total": 4,
        })
        check("POST /review/answer wrong", s3 == 200 and d3.get("correct") is False, str(d3))

    # POST /persona (persona mode)
    s, d = req("POST", "/persona", {"persona": "A helpful tutor who speaks simply."})
    check("POST /persona", s == 200 and d.get("ok"), str(d))

    # DELETE /voice (no voice -> 404)
    s, d = req("DELETE", "/voice")
    check("DELETE /voice (no voice -> 404)", s == 404, str(d))

    # Final profile check - XP should have grown
    s, d = req("GET", "/api/me")
    check("GET /api/me final", s == 200 and d.get("xp", 0) >= xp_from_word, str(d))
    print("    xp:", d.get("xp"), "level:", d.get("level"), "streak:", d.get("streak"))

    print()
    if errors:
        print("FAILED:", len(errors), "tests ->", errors)
        sys.exit(1)
    else:
        print("All", 17, "route tests passed.")

finally:
    server.terminate()
    if os.path.exists("test_routes.db"):
        os.unlink("test_routes.db")

