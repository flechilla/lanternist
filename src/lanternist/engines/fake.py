"""Stand-ins for every model (LANTERNIST_FAKE_ENGINES=1): the whole pipeline, API and UI run in
seconds with no GPU. Pictures are ffmpeg test patterns, narration is a tone as long as the words
would take to say, and video is a moving test pattern with a tone for ambience."""

import math
import struct
import wave
from pathlib import Path

from ..text import word_count
from . import ffmpeg

WORDS_PER_SECOND = 2.5


def tts(item: dict, sample_rate: int = 24000, chunk_gap: float = 0.25) -> dict:
    durs = [max(1.0, word_count(c) / WORDS_PER_SECOND) for c in item["chunks"]]
    freq = 180 + (item.get("seed", 0) * 37) % 200
    frames = bytearray()
    for k, d in enumerate(durs):
        if k:
            frames += b"\0\0" * int(sample_rate * chunk_gap)
        for s in range(int(sample_rate * d)):
            frames += struct.pack("<h", int(3000 * math.sin(2 * math.pi * freq * s / sample_rate)))
    with wave.open(item["out"], "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))
    total = sum(durs) + chunk_gap * (len(durs) - 1)
    return {
        "id": item["id"],
        "out": item["out"],
        "sample_rate": sample_rate,
        "duration": round(total, 3),
        "chunk_durations": [round(d, 3) for d in durs],
        "secs": 0.0,
    }


async def image(item: dict) -> dict:
    hue = (item["seed"] * 47) % 360
    await ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={item['width']}x{item['height']}:d=1",
            "-vf",
            f"hue=h={hue}",
            "-frames:v",
            "1",
            item["out"],
        ]
    )
    return {
        "id": item["id"],
        "out": item["out"],
        "width": item["width"],
        "height": item["height"],
        "secs": 0.0,
    }


async def video(frames: int, fps: int, width: int, height: int, out: Path) -> None:
    secs = frames / fps
    await ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={width}x{height}:r={fps}:d={secs:.3f}",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=330:d={secs:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(out),
        ]
    )
