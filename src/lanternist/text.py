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

# What a voice sample says, in each language: a line a story here could open with.
SAMPLES = {
    "en": "Once upon a time, in a lighthouse by the sea, a small grey cat watched the stars come out, one by one.",
    "es": "Había una vez, en un faro junto al mar, una gatita gris que miraba salir las estrellas, una a una.",
    "pt": "Era uma vez, em um farol à beira-mar, uma gatinha cinza que olhava as estrelas surgirem, uma a uma.",
    "fr": "Il était une fois, dans un phare au bord de la mer, une petite chatte grise qui regardait les étoiles s'allumer, une à une.",
    "de": "Es war einmal eine kleine graue Katze in einem Leuchtturm am Meer, die zusah, wie die Sterne einer nach dem anderen aufgingen.",
    "it": "C'era una volta, in un faro sul mare, una gattina grigia che guardava le stelle accendersi, una dopo l'altra.",
    "ru": "Жила-была в маяке у моря маленькая серая кошка, которая смотрела, как одна за другой зажигаются звёзды.",
    "zh": "从前，在海边的灯塔里，住着一只灰色的小猫，她看着星星一颗接一颗地亮起来。",
    "ja": "むかしむかし、海辺の灯台に小さな灰色のねこがいて、星がひとつずつ光るのを見ていました。",
    "ko": "옛날 옛적, 바닷가 등대에 작은 회색 고양이가 살았는데, 별이 하나둘 떠오르는 것을 바라보았어요.",
}

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


def tts_chunks(text: str, language: str, limit: int = MAX_CHUNK) -> list[str]:
    return [normalize_for_tts(c, language) for c in pack(text, limit)]


def word_count(text: str) -> int:
    cjk = len(re.findall(r"[぀-ヿ㐀-鿿가-힯]", text))
    return len(re.findall(r"\b\w+\b", text)) + cjk // 2
