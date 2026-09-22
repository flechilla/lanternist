"""Language-aware text helpers: sentence splitting, synthesis chunks, subtitle cues."""

import re
import unicodedata

# Qwen3-TTS takes the language as an English name.
LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}

# Every engine has a per-request ceiling and quality drifts on long passages.
MAX_CHUNK = 350
MAX_CUE = 90

# Latin punctuation needs a following space; CJK full stops don't have one.
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|(?<=[。！？])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.strip()) if s and s.strip()]


def pack(text: str, limit: int) -> list[str]:
    """Greedily pack sentences into pieces of at most `limit` characters (a sentence is never split)."""
    out, buf = [], ""
    for sent in sentences(text):
        if buf and len(buf) + len(sent) + 1 > limit:
            out.append(buf)
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
    if buf:
        out.append(buf)
    return out


def normalize_for_tts(text: str, language: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("…", "...")
    if language == "en":
        # English tokenizers trip on curly quotes and dashes; other languages keep « » „ “ and CJK marks.
        for a, b in [("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("—", " - "), ("–", "-")]:
            text = text.replace(a, b)
    return text.strip()


def tts_chunks(text: str, language: str) -> list[str]:
    return [normalize_for_tts(c, language) for c in pack(text, MAX_CHUNK)]


def word_count(text: str) -> int:
    cjk = len(re.findall(r"[぀-ヿ㐀-鿿가-힯]", text))
    return len(re.findall(r"\b\w+\b", text)) + cjk // 2
