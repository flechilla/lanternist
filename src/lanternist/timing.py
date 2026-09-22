"""Turn narration durations into the film's timeline.

Narration is recorded first, so every picture holds exactly as long as its words. A scene's slot
runs from the start of its first word to the start of the next scene's first word (the pause
belongs to the shot before); the last slot adds a tail. Crossfades are centred on slot
boundaries, so each clip carries half a crossfade of handle on each side it meets another clip.

A scene that continues the paragraph before it is another shot of the same moment: it follows the
short pause inside a paragraph, and cuts in on its first word instead of dissolving, as a film
cuts within a scene and dissolves where time or place moves on.
"""

import itertools
import math
from dataclasses import dataclass, field

from .text import MAX_CUE, pack


@dataclass
class Timeline:
    speech_starts: list[float]  # when each scene's narration starts
    bounds: list[float]  # scene boundaries b0=0 .. bN=total
    xfade: float
    cuts: list[int] = field(default_factory=list)  # boundaries (1..n-1) crossed by a cut, not a crossfade

    @property
    def n(self) -> int:
        return len(self.speech_starts)

    @property
    def total(self) -> float:
        return self.bounds[-1]

    def slot(self, i: int) -> float:
        return self.bounds[i + 1] - self.bounds[i]

    def fade(self, i: int) -> float:
        """The crossfade at boundary i: none where a cut crosses it."""
        return 0.0 if i in self.cuts else self.xfade

    def clip_start(self, i: int) -> float:
        """Where scene i's clip begins on the film timeline."""
        return 0.0 if i == 0 else self.bounds[i] - self.fade(i) / 2

    def clip_length(self, i: int) -> float:
        """Slot plus half a crossfade on every side that meets another clip with one."""
        before = self.fade(i) / 2 if i > 0 else 0.0
        after = self.fade(i + 1) / 2 if i < self.n - 1 else 0.0
        return self.slot(i) + before + after


def timeline(
    durations: list[float],
    gap: float,
    lead_in: float,
    tail: float,
    xfade: float,
    continues: list[bool] | None = None,
    shot_gap: float = 0.0,
) -> Timeline:
    """`continues[i]`: scene i is another shot of the paragraph before, `shot_gap` after it, cut to."""
    joined = continues or [False] * len(durations)
    starts, t = [], lead_in
    for i, d in enumerate(durations):
        starts.append(round(t, 3))
        t += d + (shot_gap if i + 1 < len(durations) and joined[i + 1] else gap)
    end = starts[-1] + durations[-1] + tail
    bounds = [0.0, *starts[1:], round(end, 3)]
    cuts = [i for i in range(1, len(durations)) if joined[i]]
    return Timeline(speech_starts=starts, bounds=bounds, xfade=xfade, cuts=cuts)


def ltx_frames(seconds: float, fps: int) -> int:
    """LTX wants 8k+1 frames; round up so a clip is never shorter than its slot."""
    return math.ceil(seconds * fps / 8) * 8 + 1


def shot_lengths(seconds: float, max_seconds: float) -> list[float]:
    """Split a clip longer than one generation into equal shots, each within the model's limit."""
    n = max(1, math.ceil(seconds / (max_seconds - 0.5)))
    return [seconds / n] * n


@dataclass
class ShotPlan:
    shots: list[float]  # the billed length of each shot, in the order they're chained
    paid: float  # seconds billed
    waste: float  # seconds billed past the clip, trimmed away
    hold: float  # seconds at the end held on the last frame


def plan_shots(seconds: float, lengths: list[float], hold_max: float) -> ShotPlan:
    """The cheapest billable lengths that cover a clip, for a model that bills only some lengths.

    Up to `hold_max` at the end may be the last frame held still (`video_clip` pads it), since most of
    that sits under the crossfade. Cheapest means fewest seconds billed; ties go to fewer shots, since
    every chain is a visible seam, then to the most even split. A model billing any length in a range
    (Kling's 3 to 15 s) is solved directly; a short list of lengths (Veo's 4, 6, 8) by trying them.
    """
    need = max(seconds - hold_max, 0.0)
    lengths = sorted(float(x) for x in lengths)
    steps = {round(b - a, 3) for a, b in itertools.pairwise(lengths)}
    step = steps.pop() if len(steps) == 1 else 0.0
    # On a grid of whole steps, every total is reachable and the fewest shots bill the least.
    if step and round(lengths[0] / step, 6).is_integer():
        shots = _even(need, lengths[0], lengths[-1], step)
    else:
        shots = _cheapest(need, lengths)
    paid = round(sum(shots), 3)
    return ShotPlan(shots, paid, round(max(paid - seconds, 0.0), 3), round(max(seconds - paid, 0.0), 3))


def _even(need: float, lo: float, hi: float, step: float) -> list[float]:
    n = max(1, math.ceil(need / hi - 1e-9))
    more = max(0, math.ceil((need - n * lo) / step - 1e-9))  # steps above the shortest length, in all
    base, extra = divmod(more, n)
    return [round(lo + (base + (i < extra)) * step, 3) for i in range(n)]


def _cheapest(need: float, lengths: list[float]) -> list[float]:
    most = max(1, math.ceil(need / lengths[-1] - 1e-9))
    best = ((round(most * lengths[-1], 3), most, 0.0), (lengths[-1],) * most)  # always covers it
    for n in range(1, most + 3):
        for combo in itertools.combinations_with_replacement(lengths, n):
            total = round(sum(combo), 3)
            rank = (total, n, max(combo) - min(combo))
            if total + 1e-9 >= need and rank < best[0]:
                best = (rank, combo)
    return sorted(best[1], reverse=True)


@dataclass
class Cue:
    start: float
    end: float
    text: str


def cues(
    scene_texts: list[list[str]],
    chunk_durations: list[list[float]],
    speech_starts: list[float],
    chunk_gap: float,
) -> list[Cue]:
    """Subtitle cues from the synthesis chunks' real durations, split into sentence-sized pieces.

    Within a chunk, pieces share its duration in proportion to their length.
    """
    out = []
    for chunks, durs, t in zip(scene_texts, chunk_durations, speech_starts, strict=True):
        for chunk, d in zip(chunks, durs, strict=True):
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
    return "\n".join(
        f"{i}\n{_ts(c.start, ',')} --> {_ts(c.end, ',')}\n{c.text}\n" for i, c in enumerate(cs, 1)
    )


def vtt(cs: list[Cue]) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_ts(c.start, '.')} --> {_ts(c.end, '.')}\n{c.text}\n" for c in cs)
