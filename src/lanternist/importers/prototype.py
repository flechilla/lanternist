"""Convert a prototype story (~/ai/bedtime-stories/stories) into a Storyboard.

    <name>.txt          title line, then paragraphs separated by blank lines (one scene each)
    <name>.prompts.txt  optional "STYLE:" block, then one keyframe prompt per paragraph
    <name>.cast.txt     optional cast sheet prompt
    <name>.motion.txt   optional motion + sound line per paragraph

The prototype's prompts already restate the cast in every prompt, so imported scenes list no
cast ids and the cast sheet prompt is carried over verbatim.
"""

import re
from pathlib import Path

from ..storyboard import Line, Scene, Storyboard


def _blocks(path: Path) -> list[str]:
    return [
        b.strip()
        for b in re.split(r"\n\s*\n", path.read_text(encoding="utf-8"))
        if b.strip() and not b.strip().startswith("#")
    ]


def _story(path: Path) -> tuple[str, list[str]]:
    raw = path.read_text(encoding="utf-8").strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    title = path.stem.replace("-", " ").title()
    if paras and len(paras[0].splitlines()) == 1 and not paras[0].endswith((".", "!", "?", '"')):
        title = paras.pop(0)
    return title, [" ".join(p.split()) for p in paras]


def import_story(path: str | Path, mode: str = "still", language: str = "en") -> Storyboard:
    path = Path(path)
    title, paras = _story(path)

    style, prompts = "", paras
    sidecar = path.with_suffix(".prompts.txt")
    if sidecar.is_file():
        prompts = _blocks(sidecar)
        if prompts and prompts[0].startswith("STYLE:"):
            style = prompts.pop(0)[len("STYLE:") :].strip()
    motion = [""] * len(paras)
    if path.with_suffix(".motion.txt").is_file():
        motion = _blocks(path.with_suffix(".motion.txt"))
    cast_prompt = None
    if path.with_suffix(".cast.txt").is_file():
        cast_prompt = " ".join(" ".join(b.split()) for b in _blocks(path.with_suffix(".cast.txt")))

    if not (len(prompts) == len(motion) == len(paras)):
        raise ValueError(
            f"counts differ: {len(paras)} paragraphs, {len(prompts)} prompts, {len(motion)} motion lines"
        )

    scenes = [
        Scene(
            n=i, narration=[Line(text=p)], visual=" ".join(v.split()), motion=" ".join(m.split()), mode=mode
        )
        for i, (p, v, m) in enumerate(zip(paras, prompts, motion), 1)
    ]
    return Storyboard(
        title=title,
        language=language,
        style=" ".join(style.split()),
        cast_sheet_prompt=cast_prompt,
        scenes=scenes,
    )
