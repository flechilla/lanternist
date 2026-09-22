"""What a board or a render would cost, before anything runs.

It walks the items the stages would build, through the same key helpers, so it prices exactly the
steps that would run: a cached step costs nothing. Each line is priced by its engine's own estimate
at list prices, which is also what the budget check before each remote stage uses. Before the
narration is recorded, scene lengths come from their words and the language's words per minute;
after, from the real slots, which is what the shot planner and the video price need.

Local steps cost GPU time instead of money. Money is in micro-dollars; the API shows dollars.
"""

from dataclasses import asdict, dataclass
from typing import Literal

from .engines.base import Engine, Estimate, Item
from .pipeline import LABELS, Pipeline
from .storyboard import Storyboard

Kind = Literal["board", "render"]


@dataclass
class Line:
    stage: str
    label: str
    model: str
    model_label: str
    local: bool
    steps: int  # in the stage
    todo: int  # of them not made yet
    cost_micros: int
    gpu_seconds: float
    paid_seconds: float  # video seconds billed
    waste_seconds: float  # of those, trimmed away


def _line(p: Pipeline, stage: str, eng: Engine, items: list[Item]) -> Line:
    todo = [it for it in items if not p.cached(it)]
    est = eng.estimate(todo) if todo else Estimate()
    return Line(
        stage,
        LABELS[stage],
        eng.entry.id,
        eng.entry.label,
        not eng.remote,
        len(items),
        len(todo),
        est.micros,
        est.gpu_seconds,
        est.paid_seconds,
        est.waste_seconds,
    )


def estimate(p: Pipeline, sb: Storyboard, kind: Kind) -> dict:
    """Every stage of a board, or of a whole render, with what's left to make and what it costs."""
    tts = p.tts(sb)
    narration = p.narration_items(sb, tts)
    records = [p.cached(it) for it in narration]
    durations = [
        rec["meta"]["duration"] if rec else it.params["seconds"]
        for it, rec in zip(narration, records, strict=True)
    ]
    lines: list[tuple[Line, Engine]] = [(_line(p, "narration", tts, narration), tts)]

    img = p.image(sb)
    cast_item = p.cast_item(img, sb)
    cast_rec = p.cached(cast_item) if cast_item else None
    cast = cast_rec["assets"]["image"] if cast_rec else None
    redraw = cast_item is not None and cast is None
    keyframe_items = [p.keyframe_item(img, sb, sc, cast, after=redraw) for sc in sb.scenes]
    keyframes = [rec["assets"]["image"] if (rec := p.cached(it)) else None for it in keyframe_items]
    pictures = ([cast_item] if cast_item else []) + keyframe_items
    lines.append((_line(p, "keyframes", img, pictures), img))

    if kind == "render" and any(sc.mode == "video" for sc in sb.scenes):
        vid = p.video()
        motion = p.motion_items(sb, p.timeline(durations), keyframes, vid)
        lines.append((_line(p, "motion", vid, motion), vid))

    total = sum(line.cost_micros for line, _ in lines)
    # The oldest list price behind a remote line that still has work to do.
    dates = [e.entry.price.synced for line, e in lines if e.remote and line.todo and e.entry.price.synced]
    out = {
        "kind": kind,
        "lines": [asdict(line) for line, _ in lines],
        "total_micros": total,
        "gpu_seconds": round(sum(line.gpu_seconds for line, _ in lines), 1),
        "waste_seconds": round(sum(line.waste_seconds for line, _ in lines), 3),
        "measured": all(records),  # scene lengths are the recorded narration's, not guessed from words
        "price_date": min(dates).isoformat() if dates else None,
    }
    if p.db is not None and p.story_id is not None:
        budget = p.db.budget_micros(p.story_id, p.cfg.defaults.budget_usd)
        spent = p.db.spend_micros(story_id=p.story_id)
        out |= {
            "budget_micros": budget,
            "spent_micros": spent,
            "short_micros": max(spent + total - budget, 0),
        }
    return out
