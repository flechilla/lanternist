"""Turn narration durations into the film's timeline.

Narration is recorded first, so every picture holds exactly as long as its words. A scene's slot
runs from the start of its first word to the start of the next scene's first word (the pause
belongs to the shot before); the last slot adds a tail. Crossfades are centred on slot
boundaries, so each clip carries half a crossfade of handle on each side it meets another clip.
"""

import math
from dataclasses import dataclass

from .text import MAX_CUE, pack


@dataclass
class Timeline:
    speech_starts: list[float]   # when each scene's narration starts
    bounds: list[float]          # scene boundaries b0=0 .. bN=total
    xfade: float

    @property
    def n(self) -> int:
        return len(self.speech_starts)

    @property
    def total(self) -> float:
        return self.bounds[-1]

    def slot(self, i: int) -> float:
        return self.bounds[i + 1] - self.bounds[i]

    def clip_start(self, i: int) -> float:
        """Where scene i's clip begins on the film timeline."""
        return 0.0 if i == 0 else self.bounds[i] - self.xfade / 2

    def clip_length(self, i: int) -> float:
        """Slot plus half a crossfade on every side that meets another clip."""
        handles = (i > 0) + (i < self.n - 1)
        return self.slot(i) + handles * self.xfade / 2


def timeline(durations: list[float], gap: float, lead_in: float, tail: float, xfade: float) -> Timeline:
    starts, t = [], lead_in
    for d in durations:
        starts.append(round(t, 3))
        t += d + gap
    end = starts[-1] + durations[-1] + tail
    bounds = [0.0] + starts[1:] + [round(end, 3)]
    return Timeline(speech_starts=starts, bounds=bounds, xfade=xfade)


def ltx_frames(seconds: float, fps: int) -> int:
    """LTX wants 8k+1 frames; round up so a clip is never shorter than its slot."""
    return math.ceil(seconds * fps / 8) * 8 + 1


def shot_lengths(seconds: float, max_seconds: float) -> list[float]:
    """Split a clip longer than one generation into equal shots, each within the model's limit."""
    n = max(1, math.ceil(seconds / (max_seconds - 0.5)))
    return [seconds / n] * n


@dataclass
class Cue:
    start: float
    end: float
    text: str


def cues(scene_texts: list[list[str]], chunk_durations: list[list[float]], speech_starts: list[float],
         chunk_gap: float) -> list[Cue]:
    """Subtitle cues from the synthesis chunks' real durations, split into sentence-sized pieces.

    Within a chunk, pieces share its duration in proportion to their length.
    """
    out = []
    for chunks, durs, t in zip(scene_texts, chunk_durations, speech_starts):
        for chunk, d in zip(chunks, durs):
            parts = pack(chunk, MAX_CUE)
            chars = sum(len(p) for p in parts) or 1
            c = t
            for p in parts:
                share = d * len(p) / chars
                out.append(Cue(round(c, 3), round(c + share, 3), p))
                c += share
            t += d + chunk_gap
    return out


def _ts(t: float, sep: str) -> str:
    h, rem = divmod(max(t, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", sep)


def srt(cs: list[Cue]) -> str:
    return "\n".join(f"{i}\n{_ts(c.start, ',')} --> {_ts(c.end, ',')}\n{c.text}\n" for i, c in enumerate(cs, 1))


def vtt(cs: list[Cue]) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_ts(c.start, '.')} --> {_ts(c.end, '.')}\n{c.text}\n" for c in cs)
