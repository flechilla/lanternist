"""Narration on fal.

Each chunk of a scene (`text.tts_chunks`, cut to the model's own limit) is one request, and all of a
scene's chunks go out at once. They come back as whatever the model makes (mp3, wav), are decoded
to 24 kHz mono and joined with the same pause the local worker leaves between chunks, so the scene's
wav and its chunk durations, and with them the subtitle cues, are built exactly as they are locally.
Each chunk is a step of its own, so a scene that fails halfway doesn't pay twice for the rest.

A voice is one of the model's presets, or a clone of a recording in voices/:

    qwen_tts    presets, or a clone: the recording and its transcript become a speaker embedding
                once (a step of its own, kept in the store), and every chunk carries its URL
    elevenlabs  presets; the language as its ISO code
    minimax     presets; the language as a boost
    chatterbox  a clone from the recording's URL; 300 characters a request
"""

import wave
from decimal import Decimal
from pathlib import Path

from .. import text
from ..config import Settings
from ..db import Database, to_micros
from ..registry import ModelEntry
from ..store import step_key
from ..voices import Voice, find_voice
from . import ffmpeg
from .base import Estimate, FalEngine, Item, OnItem, Output, StepContext, TtsEngine, gather_all

SAMPLE_RATE = 24000  # what the local worker writes, and what every chunk is decoded to


class VoiceError(ValueError):
    pass


def join_speech(parts: list[Path], gap: float, out: Path) -> list[float]:
    """Join decoded chunks with `gap` seconds of silence between them; returns each one's duration."""
    silence = b"\0\0" * round(SAMPLE_RATE * gap)
    durations = []
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        for k, part in enumerate(parts):
            with wave.open(str(part), "rb") as r:
                frames = r.readframes(r.getnframes())
                durations.append(round(r.getnframes() / SAMPLE_RATE, 3))
            w.writeframes((silence if k else b"") + frames)
    return durations


def chars_estimate(entry: ModelEntry, chars: list[int]) -> Estimate:
    """What narrating texts of these lengths costs at the model's price per thousand characters."""
    est = Estimate()
    for n in chars:
        thousands = Decimal(n) / 1000
        est = est + Estimate(items=1, units=thousands, micros=to_micros(thousands * entry.list_price()))
    return est


class FalTts(FalEngine, TtsEngine):
    def __init__(self, cfg: Settings, entry: ModelEntry, db: Database | None, voice: str, language: str):
        super().__init__(cfg, entry, db)
        self.language = language
        self.preset = voice if voice in entry.voices else None
        self.clip: Voice | None = None
        if self.preset is None:
            if not entry.clone or cfg.hosted_edition:  # hosted clones no recording: HOSTED_PLAN §1.9
                raise VoiceError(
                    f"“{voice}” isn't one of {entry.label}'s voices: pick one of them on the Script step"
                )
            self.clip = find_voice(cfg, voice)

    def chunks(self, words: str) -> list[str]:
        return text.tts_chunks(words, self.language, self.entry.max_chars or text.MAX_CHUNK)

    def key(self, kind: str, **inputs) -> str:
        if not self.entry.seed:
            inputs.pop("seed")  # the story's seed decides nothing a model without one makes
        return step_key(
            kind,
            engine=self.engine_id,
            options=self.options(),
            language=self.language,
            voice=self.preset or (self.clip.sha if self.clip else None),
            ref_text=self.clip.text if self.clip else None,
            chunk_gap=self.cfg.render.chunk_gap,
            **inputs,
        )

    def estimate(self, items: list[Item]) -> Estimate:
        return chars_estimate(self.entry, [sum(len(c) for c in it.params["chunks"]) for it in items])

    def arguments(self, words: str, voice: dict, seed: int) -> dict:
        family, name = self.entry.family, text.LANGUAGES[self.language]
        options = self.options()
        if family == "elevenlabs":
            return {"text": words, "voice": self.preset, "language_code": self.language, **options}
        if family == "minimax":
            setting = options.pop("voice_setting", {}) | {"voice_id": self.preset}
            return {"prompt": words, "voice_setting": setting, "language_boost": name, **options}
        seeded = {"seed": seed} if self.entry.seed else {}  # sent exactly when `key` hashes it
        if family == "chatterbox":
            a = {"text": words, "voice": voice["clip_url"], "custom_audio_language": name.lower(), **options}
            return a | seeded
        a = {"text": words, "language": name, **options} | seeded  # qwen_tts
        if self.preset:
            return a | {"voice": self.preset}
        a["speaker_voice_embedding_file_url"] = voice["embedding_url"]
        return a | ({"reference_text": self.clip.text} if self.clip and self.clip.text else {})

    async def voice(self, ctx: StepContext) -> dict:
        """What every chunk needs to speak in a cloned voice: the recording's URL, or its embedding's."""
        if self.clip is None:
            return {}
        # A reference recording stays on fal for an hour, not the day other media get.
        clip_url = await self.upload(
            ctx, f"voice-{self.clip.sha}.wav", ttl_hours=self.cfg.fal.voice_ttl_hours, path=self.clip.wav
        )
        if self.entry.family == "chatterbox":
            return {"clip_url": clip_url}
        key = step_key(
            "voice_embedding", engine=f"{self.engine_id}#clone", voice=self.clip.sha, ref_text=self.clip.text
        )
        rec = ctx.store.get_step(key)
        if rec is None:
            arguments = {"audio_url": clip_url} | (
                {"reference_text": self.clip.text} if self.clip.text else {}
            )
            res = await self.request(ctx, Item("voice", key), arguments, role="clone")
            path = await self.fetch(res.data["speaker_embedding"]["url"], ctx.work / "voice.safetensors")
            rec = ctx.store.put_step(key, {"assets": {"embedding": ctx.store.put(path)}})
        return {"embedding_url": await self.upload(ctx, rec["assets"]["embedding"])}

    async def run(self, items: list[Item], ctx: StepContext, on_item: OnItem) -> None:
        voice = await self.voice(ctx)
        await gather_all([self.speak(it, ctx, on_item, voice) for it in items])

    async def speak(self, item: Item, ctx: StepContext, on_item: OnItem, voice: dict) -> None:
        chunks, seed = item.params["chunks"], item.params["seed"]
        parts: list[Path] = [ctx.work / f"{item.id}-{k}.wav" for k in range(len(chunks))]

        async def one(k: int, words: str) -> None:
            key = step_key("tts_chunk", scene=item.key, index=k)
            rec = ctx.store.get_step(key)
            if rec is None:
                chunk = Item(f"{item.id}-{k}", key, item.scene)
                cost = chars_estimate(self.entry, [len(words)]).micros
                res = await self.request(ctx, chunk, self.arguments(words, voice, seed), estimate=cost)
                got = await self.fetch(res.data["audio"]["url"], ctx.work / f"{chunk.id}.mp3")
                rec = ctx.store.put_step(key, {"assets": {"audio": ctx.store.put(got)}})
            await ffmpeg.to_wav(ctx.store.path(rec["assets"]["audio"]), parts[k], SAMPLE_RATE)

        await gather_all([one(k, words) for k, words in enumerate(chunks)])
        out = ctx.work / f"{item.id}.wav"
        durations = join_speech(parts, self.cfg.render.chunk_gap, out)
        gaps = self.cfg.render.chunk_gap * (len(chunks) - 1)
        meta = {
            "duration": round(sum(durations) + gaps, 3),
            "chunks": chunks,
            "chunk_durations": durations,
            "sample_rate": SAMPLE_RATE,
        }
        on_item(Output(item, out, meta))
