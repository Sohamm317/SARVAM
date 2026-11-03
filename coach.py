"""Language coach prompt and LLM output parsing.

The coach generates natural conversational responses.
Vocabulary items can be supplied at the end under ---VOCAB--- or as JSON.
Even if the model outputs truncated or malformed JSON, parse_coach_response
cleanly extracts normal human language so the user never sees raw code/JSON.
"""

import json
import re

# ── System prompt ──

COACH_SYSTEM_PROMPT = """\
You are a warm, encouraging, and natural language coach helping a student learn {target_language}.

HOW TO COMMUNICATE:
1. Speak in natural, everyday conversational language, like a friendly personal tutor sitting beside the student.
2. Keep your replies concise (2 to 3 sentences), spoken-friendly, and engaging.
3. Answer the student's questions, teach correct everyday expressions in {target_language}, explain nuances, and gently correct mistakes.
4. When teaching phrases or sentences in {target_language}, write them directly in native script.
5. DO NOT repeat the phonetic/romanized version in parentheses in your conversational message (do NOT write 'શબ્દ (shabd)'). Keep the spoken message clean and singular so the voice synthesizer does not repeat redundant sentences in multiple languages.
6. Put any romanized pronunciation strictly in the ---VOCAB--- section at the bottom so it appears on the visual flashcards only.

VOCABULARY WORDS (Optional):
If you introduced 1 to 3 key new vocabulary words or phrases in this turn that the student should practice, list them at the very end separated by ---VOCAB--- like this:
---VOCAB---
native_word | romanization | English meaning
---END---
(Only include 1-3 new words actually taught in this reply. Keep the main message completely natural.)
"""

LANGUAGE_NAMES = {
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


def build_coach_system(target_language: str) -> str:
    """Build the system prompt for the language coach."""
    lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    return COACH_SYSTEM_PROMPT.format(
        target_language=lang_name,
        language_code=target_language,
    )


def build_coach_messages(target_language: str, history: list[dict], max_history: int = 20) -> list[dict]:
    """Build the message list for a coach chat call."""
    system = build_coach_system(target_language)
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-max_history:])
    return messages


# ── Response parsing ──

def parse_coach_response(raw_text: str, default_lang: str = "hi-IN") -> dict:
    """
    Parse the LLM's response into {reply, vocab}.
    Guarantees the user gets clean, natural human language as output,
    never raw JSON syntax, quotes, or structured artifacts.
    """
    text = (raw_text or "").strip()
    if not text:
        return {"reply": "", "vocab": []}

    # 1. Try full JSON parse if the model responded with valid JSON
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "reply" in data:
            reply = str(data.get("reply") or "").strip()
            raw_vocab = data.get("vocab") or []
            vocab = []
            for item in raw_vocab:
                if isinstance(item, dict) and item.get("text") and item.get("meaning"):
                    vocab.append({
                        "text": str(item["text"]).strip()[:50],
                        "romanized": str(item.get("romanized") or "").strip()[:50],
                        "meaning": str(item["meaning"]).strip()[:150],
                        "language_code": str(item.get("language_code") or default_lang).strip(),
                    })
            return {"reply": reply, "vocab": vocab}
    except Exception:
        pass

    # 2. Markdown json code block
    m_code = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m_code:
        try:
            data = json.loads(m_code.group(1))
            if isinstance(data, dict) and "reply" in data:
                return parse_coach_response(m_code.group(1), default_lang)
        except Exception:
            pass

    # 3. Truncated or malformed JSON with "reply": (prevents raw JSON leakage)
    if '"reply"' in text:
        m_reply = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*?)(?:"\s*,\s*"vocab"|"\s*\}|$)', text, re.DOTALL)
        if not m_reply:
            m_reply = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)', text, re.DOTALL)
        reply = ""
        if m_reply:
            raw_val = m_reply.group(1)
            try:
                reply = json.loads('"' + raw_val + '"')
            except Exception:
                reply = raw_val.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
        
        # Salvage completed vocab cards from the JSON array
        vocab = []
        for vm in re.finditer(r'\{[^{}]*"text"\s*:\s*"([^"]+)"[^{}]*\}', text):
            try:
                item = json.loads(vm.group(0))
                if item.get("text") and item.get("meaning"):
                    vocab.append({
                        "text": str(item["text"]).strip()[:50],
                        "romanized": str(item.get("romanized") or "").strip()[:50],
                        "meaning": str(item["meaning"]).strip()[:150],
                        "language_code": str(item.get("language_code") or default_lang).strip(),
                    })
            except Exception:
                pass
        
        if reply:
            return {"reply": reply.strip(), "vocab": vocab}

    # 4. Delimited vocab format (---VOCAB--- or Vocabulary:)
    split_match = re.split(r'---VOCAB---|(?i:\bvocabulary\s*:\s*\n)', text, maxsplit=1)
    if len(split_match) == 2:
        reply = split_match[0].strip()
        vocab_section = split_match[1]
        vocab = []
        for line in vocab_section.splitlines():
            line = line.strip().lstrip('-*•0123456789. ')
            if not line or line.startswith('---'):
                continue
            parts = [p.strip() for p in re.split(r'[|:]', line) if p.strip()]
            if len(parts) >= 3:
                vocab.append({
                    "text": parts[0][:50],
                    "romanized": parts[1][:50],
                    "meaning": parts[2][:150],
                    "language_code": default_lang,
                })
            elif len(parts) == 2:
                # check if parts[0] contains (romanized)
                m_rom = re.search(r'^(.*?)\s*\((.*?)\)$', parts[0])
                if m_rom:
                    vocab.append({
                        "text": m_rom.group(1).strip()[:50],
                        "romanized": m_rom.group(2).strip()[:50],
                        "meaning": parts[1][:150],
                        "language_code": default_lang,
                    })
                else:
                    vocab.append({
                        "text": parts[0][:50],
                        "romanized": "",
                        "meaning": parts[1][:150],
                        "language_code": default_lang,
                    })
        return {"reply": reply, "vocab": vocab}

    # 5. Fallback: clean natural text (strip any accidental trailing/leading JSON braces or artifacts)
    clean = re.sub(r'^\s*\{\s*"reply"\s*:\s*"?', '', text)
    clean = re.sub(r'"?\s*,\s*"vocab".*$', '', clean, flags=re.DOTALL)
    clean = clean.strip().rstrip('"}')
    return {"reply": clean, "vocab": []}
