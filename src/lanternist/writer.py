"""The writer: a one-line idea becomes a storyboard, with the local LLM or an OpenRouter model (llm.py).

Two passes. Pass 1 writes the story as plain prose in the story's language, because prose written
into a JSON field comes out worse. Pass 2 reads that story and returns, through schema-constrained
output, the cast and each paragraph's English picture, motion and sound prompts. Narration is
taken verbatim from pass 1, so the LLM can't drift it while formatting.
"""

import random
import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import llm as llms
from .config import Settings
from .db import to_usd
from .storyboard import (
    Camera,
    CastKind,
    CastMember,
    Effort,
    Line,
    Mode,
    Models,
    Place,
    Scene,
    Storyboard,
    WriterId,
    slugify,
)
from .text import LANGUAGES, sentences, word_count

STYLES = {
    "watercolour": "soft watercolour storybook illustration, gentle washes of colour, visible paper texture, "
    "warm light, no text",
    "3d_film": "3D animated feature film still, stylized characters with big expressive eyes, soft global "
    "illumination, vibrant warm colors, painterly detailed backgrounds, cinematic composition, no text",
    "paper_cutout": "layered paper cut-out illustration, handmade craft textures, soft shadows between the "
    "layers, no text",
    "clay": "claymation stop-motion film still, sculpted plasticine characters, miniature handmade set, soft "
    "studio lighting, no text",
    "ink_pencil": "ink and coloured pencil illustration, expressive linework, light cross-hatching, muted "
    "palette, no text",
    "anime": "hand-drawn anime film still, painted backgrounds, soft cel shading, luminous skies, no text",
}

AUDIENCES = {
    "toddlers": "toddlers aged 2 to 4: very simple words, short sentences, gentle repetition, warm and safe, "
    "no peril at all",
    "kids_5_8": "children aged 5 to 8: simple vocabulary, mild peril at most, always a kind resolution",
    "kids_9_12": "children aged 9 to 12: age-appropriate conflict and themes, richer vocabulary",
    "teens": "teenagers: real stakes and emotional depth, nothing graphic",
    "adults": "adults: any genre, literary quality",
}

KINDS = {
    "bedtime": "a bedtime story whose last third slows down and winds toward sleep",
    "adventure": "an adventure with a clear goal, obstacles and a satisfying return",
    "funny": "a funny story with playful situations and a warm ending",
    "learn": "a story that teaches something true and interesting along the way",
    "fable": "a fable with a clear, gentle moral that the story shows rather than states",
}

# Narration speed used to size a story; corrected later from measured narrations.
WPM = {
    "en": 150,
    "es": 140,
    "pt": 140,
    "fr": 145,
    "it": 145,
    "de": 130,
    "ru": 125,
    "zh": 240,
    "ja": 240,
    "ko": 170,
}
WORDS_PER_SCENE = 32  # ~13 s of narration: one picture, and within one LTX generation


CHARS_PER_WORD = 6  # five letters and a space, about, in the alphabetic languages


def wpm(language: str) -> int:
    return WPM.get(language, 140)


def narration_seconds(words: str, language: str) -> float:
    """How long narrating `words` takes, before it's recorded: for estimates."""
    return round(word_count(words) * 60 / wpm(language), 1)


ALWAYS = (
    "Never include sexual content, real identifiable people, public figures, or real brands. "
    "No violence beyond what the audience allows."
)


class Brief(BaseModel):
    idea: str
    language: str = "en"
    audience: str = "kids_5_8"
    kind: str = "bedtime"
    minutes: float = 3.0
    style: str = "watercolour"
    notes: str = ""
    mode: Literal["still", "video", "hybrid"] = "still"
    voice: str = "demo"
    writer: WriterId = Field(
        "", description="ollama/<model> or openrouter/<model id>; empty is the default writer"
    )
    effort: Effort | None = Field(None, description="reasoning effort; None is the model's default")

    @property
    def target_words(self) -> int:
        return int(self.minutes * wpm(self.language))

    @property
    def scenes(self) -> int:
        return max(3, round(self.target_words / WORDS_PER_SCENE))


class WriterCast(BaseModel):
    id: str = Field(description="short lowercase ascii slug of the name, e.g. 'luna'")
    name: str = Field(description="the name the story uses")
    look: str = Field(
        description="English, 15-35 words. A character: species or age, build, colours, clothing, one "
        "distinctive accessory. An object: shape, material, colours, size, markings. Concrete and "
        "visual. No name, no personality."
    )
    kind: CastKind = Field(description="'character', or 'object' for a thing the story turns on")


class WriterPlace(BaseModel):
    id: str = Field(description="short lowercase ascii slug, e.g. 'windmill'")
    name: str = Field(description="what the story calls it")
    look: str = Field(
        description="English, 15-35 words: what fixes the setting: its layout, materials, colours and "
        "landmarks. No people, no weather, no time of day."
    )


class WriterShot(BaseModel):
    sentences: int = Field(description="how many of the paragraph's sentences the shot covers, in order")
    visual: str = Field(
        description="English image prompt for the shot's first frame, 30-70 words: shot size and angle "
        "first, then who is where doing what, then the light. Characters, objects and places by name only."
    )
    motion: str = Field(
        description="English, 2-4 sentences in present tense: the shot as one continuous take, in time "
        "order: the main action, what else moves, and one camera move with its size and speed."
    )
    sound: str = Field(
        description="English, the shot's own sounds, specific, e.g. 'wind gusting over wet sand, a paper "
        "tail snapping'. Never speech, singing or music."
    )
    cast: list[str] = Field(description="ids of the characters and objects visible in this picture")
    place: str = Field(description="id of the place it's set in, or '' for a place seen only once")
    camera: Camera = Field(description="the move when the shot is shown as a still picture")
    key_moment: bool = Field(description="true for about one shot in three: the most dramatic or magical")


class WriterScene(BaseModel):
    n: int
    shots: list[WriterShot] = Field(
        description="one to three shots, covering the paragraph's sentences in order"
    )


class WriterBoard(BaseModel):
    title: str = Field(description="a short, evocative title in the story's own language")
    cast: list[WriterCast]
    places: list[WriterPlace]
    scenes: list[WriterScene]


class RewrittenScene(BaseModel):
    narration: str
    visual: str
    motion: str
    sound: str
    cast: list[str]
    camera: Camera


def inline_schema(model: type[BaseModel]) -> dict:
    """Pydantic's schema with every $ref inlined; grammar-constrained decoders prefer it flat."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node, in_properties=False):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            # Drop pydantic's "title" annotations, but not a property that happens to be called title.
            return {
                k: walk(v, k == "properties")
                for k, v in node.items()
                if in_properties or not (k == "title" and isinstance(v, str))
            }
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


_TITLE = re.compile(r"^\W*(title|t[íi]tulo|titre|titel|titolo)\s*:\s*(.+)$", re.IGNORECASE)


def _parse_story(raw: str) -> tuple[str | None, list[str]]:
    """(title or None, paragraphs). The title is a 'TITLE:' line, or a short first line without a full stop."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    title, kept = None, []
    for line in raw.splitlines():
        m = _TITLE.match(line.replace("*", "").strip())
        if m and title is None:
            title = m.group(2).strip(" #*\"'")
        else:
            kept.append(line)
    blocks = [
        " ".join(b.replace("*", "").replace("#", "").split()) for b in re.split(r"\n\s*\n", "\n".join(kept))
    ]
    blocks = [b for b in blocks if b]
    if (
        title is None
        and blocks
        and word_count(blocks[0]) <= 12
        and not blocks[0].endswith((".", "!", "?", "…"))
    ):
        title = blocks.pop(0).strip("\"'")
    return title, [p for p in blocks if word_count(p) >= 3]


def story_prompt(b: Brief) -> tuple[str, str]:
    lang = _language_name(b.language)
    system = (
        f"You are a master storyteller who writes stories to be read aloud and illustrated. "
        f"You write natively in {lang}. {ALWAYS}"
    )
    user = (
        f"Write {KINDS.get(b.kind, b.kind)} for {AUDIENCES.get(b.audience, b.audience)}.\n\n"
        f"Idea: {b.idea}\n"
        + (f"Also include: {b.notes}\n" if b.notes else "")
        + f"\nWrite it in {lang}. Length is strict: {b.target_words} words in total (it is narrated in "
        f"{b.minutes:g} minutes), in exactly {b.scenes} paragraphs. Every paragraph has three or four "
        f"sentences, about {WORDS_PER_SCENE} words; never fewer than {WORDS_PER_SCENE - 8} or more than "
        f"{WORDS_PER_SCENE + 8}. Each paragraph is one illustrated scene, "
        f"so each should show one clear moment that a single picture can capture. Keep the main characters "
        f"few (one to four) and consistent.\n\n"
        f"Output format: a first line 'TITLE: <the title>', a blank line, then the paragraphs separated by "
        f"blank lines. No headings, no scene numbers, no notes, nothing else."
    )
    return system, user


def board_prompt(b: Brief, title: str | None, paras: list[str]) -> tuple[str, str]:
    system = (
        "You are the director and storyboard artist of an illustrated, narrated film. You cut a story into "
        "shots and write the prompts AI image and video models draw and animate them from. All prompts are "
        f"in English, whatever the story's language. {ALWAYS}"
    )
    numbered = "\n\n".join(
        f"[{i}]\n" + "\n".join(f"  {j}. {s}" for j, s in enumerate(sentences(p), 1))
        for i, p in enumerate(paras, 1)
    )
    slow = (
        " In the last third, as the story winds toward sleep, use fewer, longer shots and slower movement."
        if b.kind == "bedtime"
        else ""
    )
    user = (
        f"Story: {title or '(untitled)'}\nAudience: {AUDIENCES.get(b.audience, b.audience)}\n\n{numbered}\n\n"
        f"Return the cast, the places and exactly {len(paras)} scenes, one per numbered paragraph, in order "
        f"(n = 1..{len(paras)}).\n\n"
        "Cast: every recurring character (kind 'character'), and every object the story turns on that must "
        "look the same in every picture (kind 'object': a kite, a lantern, a toy boat). What a character "
        "wears or always carries belongs in their look. Looks are added to every prompt automatically, so "
        "prompts name characters and objects by name only.\n"
        "Places: every setting seen in more than one shot, with a look that fixes it. A shot names its "
        "place's id, or '' for a place seen once, which its visual describes.\n\n"
        "Shots: split each paragraph into one to three shots. A shot covers whole sentences, in order: "
        "'sentences' counts them, and a paragraph's counts add up to its number of sentences. A shot lasts "
        "as long as its sentences take to read aloud, so every shot needs at least 12 words: never give a "
        "short sentence a shot of its own. Most paragraphs get two shots; a short or quiet one stays one. "
        "The shots of a paragraph are one continuous scene, "
        "cut like a film: change the shot size or angle between them (a wide shot, then a close-up on a face "
        f"or hands), and keep the place, light and objects the same.{slow}\n"
        "- visual: the first frame, one moment in one framing (never 'then'). Start with the shot size and "
        "angle (wide establishing shot, medium shot, close-up, low angle, over the shoulder) and vary them "
        "across the film. Then who is where doing what, naming every character in the shot each time: never "
        "'the children' or 'they', which draws more of them, and no one the story doesn't name. Then the "
        "light. Show feelings through faces and bodies. No readable text, signs or labels.\n"
        "- motion: the shot as one continuous take, in time order: the characters' one main action, gentle "
        "and physically possible; what else moves (hair, cloth, water, leaves, light); and one camera move with "
        "its size and speed ('the camera slowly pushes in a little', 'the camera holds still'). Nothing fast, "
        "spinning or twisting. Nobody talks.\n"
        "- sound: what this shot sounds like, concrete and specific. Never speech, singing or music.\n"
        "- camera: the move used when the shot is shown as a still picture; match the motion's camera move."
    )
    return system, user


def _spent(reply: llms.Reply) -> str:
    return f" (${to_usd(reply.cost_micros):.4f})" if reply.cost_micros else ""


async def write_storyboard(
    cfg: Settings,
    b: Brief,
    emit: Callable[[str], None] | None = None,
    calls: llms.Calls | None = None,
) -> Storyboard:
    emit = emit or (lambda m: None)
    llm = llms.make(cfg, b.writer, b.effort, calls)
    async with llm.session():
        emit(
            f"writing the story with {llm.id} ({b.scenes} scenes, ~{b.target_words} words, "
            f"{_language_name(b.language)})"
        )
        system, user = story_prompt(b)
        reply = await llm.chat(system, user, name="story")
        raw = reply.text
        title, paras = _parse_story(raw)
        if len(paras) < 2:
            raise RuntimeError("the writer returned no usable paragraphs")
        words = sum(word_count(p) for p in paras)
        emit(f"story written: {len(paras)} paragraphs, {words} words{_spent(reply)}")
        for _ in range(2):
            if abs(words / b.target_words - 1) <= 0.15:
                break
            per = words / max(len(paras), 1)
            advice = (
                "longer: add sensory detail and small actions, one more sentence per paragraph"
                if words < b.target_words
                else "shorter: cut repetition and side details"
            )
            emit(f"{words} words against a target of {b.target_words}: revising")
            revise = (
                f"{user}\n\nYour draft below has {words} words in {len(paras)} paragraphs "
                f"(about {per:.0f} words each). It must be {b.target_words} words in {b.scenes} paragraphs of "
                f"about {WORDS_PER_SCENE} words. Make it {advice}. Keep the title, characters and plot. Same "
                f"output format.\n\n{raw}"
            )
            reply = await llm.chat(system, revise, temperature=0.5, name="story")
            raw2 = reply.text
            t2, p2 = _parse_story(raw2)
            w2 = sum(word_count(p) for p in p2)
            if len(p2) >= 2 and abs(w2 / b.target_words - 1) < abs(words / b.target_words - 1):
                raw, title, paras, words = raw2, t2 or title, p2, w2
                emit(f"revised: {len(paras)} paragraphs, {words} words{_spent(reply)}")

        emit("storyboarding: cast, pictures, motion and sound")
        schema = inline_schema(WriterBoard)
        system, user = board_prompt(b, title, paras)
        wb, error = None, None
        for _ in range(2):
            prompt = user if not error else f"{user}\n\nYour previous answer was invalid: {error}. Fix it."
            reply = await llm.chat(system, prompt, schema=schema, temperature=0.4, name="storyboard")
            try:
                wb = WriterBoard.model_validate_json(_json_text(reply.text))
                if len(wb.scenes) != len(paras):
                    raise ValueError(f"returned {len(wb.scenes)} scenes for {len(paras)} paragraphs")
                if empty := [ws.n for ws in wb.scenes if not ws.shots]:
                    raise ValueError(f"scenes {empty} have no shots")
                break
            except (ValidationError, ValueError) as e:
                error = str(e)[:500]
                emit(f"storyboard invalid ({error[:120]}), retrying")
                wb = None
        if wb is None:
            raise RuntimeError(f"the storyboard didn't validate twice: {error}")
    sb = assemble(b, title or wb.title, paras, wb)
    emit(
        f"storyboard ready: {len(sb.cast)} in the cast, {len(sb.places)} places, {len(sb.scenes)} shots "
        f"in {len(paras)} scenes{_spent(reply)}"
    )
    sb.models = Models(writer=llm.id, writer_effort=b.effort)
    return sb


def _json_text(text: str) -> str:
    """The JSON object in a reply; a few models wrap structured output in a code fence anyway."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return m.group(1) if m else text


_NOT_AMBIENCE = re.compile(
    r"\b(voice|voices|speech|speak\w*|talk\w*|whisper\w*|sing\w*|song|music\w*|"
    r"melod\w*|chime\w*|meow\w*|narrat\w*)\b",
    re.IGNORECASE,
)


def ambience_only(sound: str) -> str:
    """The narration is laid on top, so the video model's sound bed must hold no voices or music.

    Drops every comma-separated clause naming one, plus a short fragment just before it, which is
    usually the first half of an adjective list ("a soft, warm voice").
    """
    pieces = [p.strip() for p in re.split(r"[,;.]", sound) if p.strip()]
    bad = [bool(_NOT_AMBIENCE.search(p)) for p in pieces]
    keep = [
        p
        for i, p in enumerate(pieces)
        if not bad[i] and not (i + 1 < len(pieces) and bad[i + 1] and len(p.split()) <= 3)
    ]
    return ", ".join(keep) or "soft room tone"


MIN_SHOT_WORDS = 8  # about three seconds read aloud: less can't hold a picture, so it joins the shot before


def split_shots(paragraph: str, shots: list[WriterShot]) -> list[tuple[str, WriterShot]]:
    """Each shot's narration: the sentences it covers, in order. Counts that don't add up are mended,
    not refused: the last shot takes what's left, a shot left with nothing is dropped, and a shot too
    short to hold a picture joins its neighbour."""
    said = sentences(paragraph)
    out: list[tuple[str, WriterShot]] = []
    i = 0
    for k, shot in enumerate(shots):
        take = len(said) - i if k == len(shots) - 1 else max(shot.sentences, 1)
        part = " ".join(said[i : i + take])
        i += take
        if not part:
            break
        if out and word_count(part) < MIN_SHOT_WORDS:
            out[-1] = (f"{out[-1][0]} {part}", out[-1][1])
        else:
            out.append((part, shot))
    if len(out) > 1 and word_count(out[0][0]) < MIN_SHOT_WORDS:
        out[:2] = [(f"{out[0][0]} {out[1][0]}", out[0][1])]
    return out


def assemble(b: Brief, title: str, paras: list[str], wb: WriterBoard) -> Storyboard:
    cast: list[CastMember] = []
    ids: set[str] = set()
    for c in wb.cast:
        cid = slugify(c.id or c.name) or f"c{len(cast) + 1}"
        if cid not in ids:
            ids.add(cid)
            cast.append(CastMember(id=cid, name=c.name.strip(), look=c.look.strip(), kind=c.kind))
    by_name = {c.name.lower(): c.id for c in cast}
    places: list[Place] = []
    for pl in wb.places:
        pid = slugify(pl.id or pl.name)
        if pid and pid not in {p.id for p in places}:
            places.append(Place(id=pid, name=pl.name.strip(), look=pl.look.strip()))
    place_ids = {p.id for p in places}
    shots = [
        (i, j, words, ws)
        for i, (p, scene) in enumerate(zip(paras, wb.scenes, strict=True))
        for j, (words, ws) in enumerate(split_shots(p, scene.shots))
    ]
    # Hybrid animates only the peaks: about 30% of shots, spread across the story's key moments.
    marked = [k for k, (*_, ws) in enumerate(shots) if ws.key_moment]
    k = max(1, round(len(shots) * 0.3))
    if not marked:
        marked = [len(shots) * 2 // 3]
    if len(marked) > k:
        marked = [marked[round(j * (len(marked) - 1) / (k - 1))] for j in range(k)] if k > 1 else [marked[-1]]
    video = set(marked)
    scenes = []
    for n, (_, j, words, ws) in enumerate(shots, 1):
        members = []
        for ref in ws.cast:
            found = slugify(ref) if slugify(ref) in ids else by_name.get(ref.lower())
            if found and found not in members:
                members.append(found)
        mode: Mode = ("video" if n - 1 in video else "still") if b.mode == "hybrid" else b.mode
        # A still with a static camera is a slide; stills always get a move ("auto" alternates in and out).
        camera = "auto" if mode == "still" and ws.camera == "static" else ws.camera
        scenes.append(
            Scene(
                n=n,
                narration=[Line(text=words)],
                visual=ws.visual.strip(),
                motion=ws.motion.strip(),
                sound=ambience_only(ws.sound),
                cast=members,
                place=slugify(ws.place) if slugify(ws.place) in place_ids else "",
                camera=camera,
                mode=mode,
                continues=j > 0,
            )
        )
    return Storyboard(
        title=title,
        language=b.language,
        audience=b.audience if b.audience in AUDIENCES else "adults",
        kind=b.kind,
        style=STYLES.get(b.style, b.style),
        voice=b.voice,
        seed=random.randint(1, 99_999),
        cast=cast,
        portraits=True,
        places=places,
        scenes=scenes,
    )


async def rewrite_scene(
    cfg: Settings,
    sb: Storyboard,
    n: int,
    instruction: str,
    calls: llms.Calls | None = None,
) -> Scene:
    """Rewrite one scene with the story's own writer; the LLM sees the whole storyboard so the story stays consistent."""
    scene = next(s for s in sb.scenes if s.n == n)
    lang = _language_name(sb.language)
    system = (
        f"You edit one scene of an illustrated, narrated story. Narration stays in {lang}; visual, motion "
        f"and sound prompts stay in English and refer to characters by name only. {ALWAYS}"
    )
    user = (
        f"The whole storyboard, for context:\n{sb.model_dump_json(exclude={'cast_sheet_prompt', 'models'})}\n\n"
        f"Rewrite scene {n} following this instruction: {instruction}\n"
        f"Keep it consistent with the scenes before and after it. Return the full rewritten scene."
    )
    llm = llms.make(cfg, sb.models.writer, sb.models.writer_effort, calls)
    async with llm.session():
        reply = await llm.chat(
            system, user, schema=inline_schema(RewrittenScene), temperature=0.6, name="scene"
        )
    r = RewrittenScene.model_validate_json(_json_text(reply.text))
    ids = {c.id for c in sb.cast}
    return scene.model_copy(
        update={
            "narration": [Line(text=" ".join(r.narration.split()))],
            "visual": r.visual.strip(),
            "motion": r.motion.strip(),
            "sound": r.sound.strip(),
            "cast": [c for c in r.cast if c in ids],
            "camera": r.camera,
        }
    )
