"""Every picture and motion prompt is built here, so the character lock is applied the same way everywhere.

The prototype found that restating each character's look in every prompt is what keeps the cast
consistent between shots. Rather than trusting the writer to restate them, the builder appends
the looks of the characters a scene lists, and likewise of the objects the story turns on and of
the place a scene is set in: a "red kite" left to the image model can come out as the bird.
"""

from .storyboard import CastKind, CastMember, Scene, Storyboard

VIDEO_SUFFIX = "No dialogue, no speech, no music."
# The ComfyUI template's own negative bans "cartoon", which is wrong for an animated film.
VIDEO_NEGATIVE = (
    "pc game, console game, video game, ugly, deformed, blurry, text, watermark, speech, talking, music"
)
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth"]


def _clean(s: str) -> str:
    return s.strip().rstrip(".").strip()


def _members(sb: Storyboard, scene: Scene, kind: CastKind) -> list[CastMember]:
    by_id = {c.id: c for c in sb.cast}
    return [by_id[c] for c in scene.cast if c in by_id and by_id[c].kind == kind]


def _looks(members: list[CastMember], numbered: bool = False) -> str:
    return "; ".join(
        f"{m.name}{f' (image {i})' if numbered else ''}, {_clean(m.look)}" for i, m in enumerate(members, 1)
    )


def scene_picture(sb: Storyboard, scene: Scene, numbered: bool = False) -> str:
    """The scene's visual with its characters', objects' and place's looks restated, without the style
    suffix. `numbered`: each character is drawn from their own reference picture, in the order they're
    listed, so they're named by it (FLUX.2 follows "image 1", "image 2") as well as by their look."""
    parts = [_clean(scene.visual)]
    if characters := _members(sb, scene, "character"):
        parts.append(f"Characters: {_looks(characters, numbered)}")
    if things := _members(sb, scene, "object"):
        parts.append(f"Objects: {_looks(things)}")
    if place := next((p for p in sb.places if p.id == scene.place), None):
        parts.append(f"Setting: {_clean(place.look)}")
    return ". ".join(parts)


def keyframe(sb: Storyboard, scene: Scene, numbered: bool = False) -> str:
    prompt = scene_picture(sb, scene, numbered)
    if numbered:
        # Given a portrait per character, klein tends to draw one of them twice unless told the count.
        names = [m.name for m in _members(sb, scene, "character")]
        if len(names) == 1:
            prompt += (
                f". {names[0]} is the only character in the picture, shown once. Take only who they are "
                "from the reference picture, not the pose or plain background"
            )
        else:
            prompt += (
                f". {', '.join(names[:-1])} and {names[-1]} are the only characters in the picture, each "
                "shown once. Take only who they are from the reference pictures, not their poses or plain "
                "backgrounds"
            )
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
    elif sb.characters:
        n = len(sb.characters)
        if n == 1:
            lead = (
                "A character sheet on a plain soft neutral background: one character standing "
                "full length, shown head to toe facing forward."
            )
        else:
            lead = (
                f"A character sheet on a plain soft neutral background: {n} characters standing "
                f"full length in a row, evenly spaced, each shown head to toe facing forward."
            )
        people = " ".join(
            f"{ORDINALS[i] if i < len(ORDINALS) else 'Next'}, {_clean(c.look)}."
            for i, c in enumerate(sb.characters)
        )
        body = f"{lead} {people} Consistent proportions, clear separation between the figures, no text and no labels"
    else:
        return None
    return f"{body}, {sb.style.strip()}" if sb.style else body


def portrait(sb: Storyboard, member: CastMember) -> str:
    """One character alone, drawn from the cast sheet: the reference for every picture they're in, so a
    picture is shown only who is in it."""
    n = len(sb.characters)
    i = sb.characters.index(member)
    which = ORDINALS[i].lower() if i < len(ORDINALS) else f"number {i + 1}"
    body = (
        f"Of the {n} characters in the reference picture, show only the {which} from the left: "
        f"{_clean(member.look)}. Alone, full length from head to toe, facing forward, centred on a plain "
        "soft neutral background. Exactly the same face, colours, clothes and proportions as in the "
        "reference. No other characters, no text and no labels"
    )
    return f"{body}, {sb.style.strip()}" if sb.style else body
