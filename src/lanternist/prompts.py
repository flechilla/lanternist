"""Every picture and motion prompt is built here, so the character lock is applied the same way everywhere.

The prototype found that restating each character's look in every prompt is what keeps the cast
consistent between shots. Rather than trusting the writer to restate them, the builder appends
the looks of the characters a scene lists.
"""

from .storyboard import Scene, Storyboard

VIDEO_SUFFIX = "No dialogue, no speech, no music."
# The ComfyUI template's own negative bans "cartoon", which is wrong for an animated film.
VIDEO_NEGATIVE = ("pc game, console game, video game, ugly, deformed, blurry, text, watermark, "
                  "speech, talking, music")
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth"]


def _clean(s: str) -> str:
    return s.strip().rstrip(".").strip()


def _looks(sb: Storyboard, scene: Scene) -> str:
    by_id = {c.id: c for c in sb.cast}
    looks = [f"{by_id[c].name}, {_clean(by_id[c].look)}" for c in scene.cast if c in by_id]
    return "; ".join(looks)


def scene_picture(sb: Storyboard, scene: Scene) -> str:
    """The scene's visual with its characters' looks restated, without the style suffix."""
    prompt = _clean(scene.visual)
    looks = _looks(sb, scene)
    return f"{prompt}. Characters: {looks}" if looks else prompt


def keyframe(sb: Storyboard, scene: Scene) -> str:
    prompt = scene_picture(sb, scene)
    return f"{prompt}, {sb.style.strip()}" if sb.style else prompt


def video(sb: Storyboard, scene: Scene) -> str:
    parts = [scene_picture(sb, scene) + "."]
    for extra in (scene.motion, scene.sound):
        if extra.strip():
            parts.append(extra.strip())
    if sb.style:
        parts.append(_clean(sb.style) + ".")
    parts.append(VIDEO_SUFFIX)
    return " ".join(parts)


def cast_sheet(sb: Storyboard) -> str | None:
    if sb.cast_sheet_prompt:
        body = sb.cast_sheet_prompt.strip()
    elif sb.cast:
        n = len(sb.cast)
        if n == 1:
            lead = ("A character sheet on a plain soft neutral background: one character standing "
                    "full length, shown head to toe facing forward.")
        else:
            lead = (f"A character sheet on a plain soft neutral background: {n} characters standing "
                    f"full length in a row, evenly spaced, each shown head to toe facing forward.")
        people = " ".join(f"{ORDINALS[i] if i < len(ORDINALS) else 'Next'}, {_clean(c.look)}."
                          for i, c in enumerate(sb.cast))
        body = f"{lead} {people} Consistent proportions, clear separation between the figures, no text and no labels"
    else:
        return None
    return f"{body}, {sb.style.strip()}" if sb.style else body
