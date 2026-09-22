# Lanternist

A one-line idea in, a narrated story film out, made entirely with models on this machine.

The local LLM writes the story, Qwen3-TTS narrates it, FLUX.2 [klein] draws a cast sheet and one keyframe
per scene, and LTX-2.5 animates the scenes you mark as video. ffmpeg then mixes it all into an MP4
with the narration, the scenes' ambience and subtitles.

## Run it

```bash
uv sync
uv run lanternist doctor        # every check should be ✓
cd web && pnpm install && pnpm build && cd ..
uv run lanternist serve         # http://127.0.0.1:8420
```

In the app:

1. Write a story from an idea.
2. Edit the script.
3. Prepare the board (narration, cast sheet, keyframes).
4. Re-roll any picture and pick which scenes are video.
5. Render.

Everything also works from the command line:

```bash
uv run lanternist write "A lighthouse cat afraid of the dark" --lang es --minutes 3 --mode hybrid -o luna.json
uv run lanternist board luna.json      # narration + cast sheet + keyframes, to review
uv run lanternist render luna.json     # the film -> ~/Lanternist/films/<title>.mp4
uv run lanternist import ~/ai/bedtime-stories/stories/maya-and-the-mountain.txt --mode video
```

## What it uses

| Stage | Model | Runs as |
|---|---|---|
| Story + storyboard | Ollama `qwen3.8` | HTTP to `ollama serve` |
| Narration | Qwen3-TTS 1.7B | a worker in `~/ai/bedtime-stories/engines/qwen3tts/.venv` |
| Cast sheet + keyframes | FLUX.2 [klein] 9B | a worker in `~/ai/qwen-image-2.1/.venv` |
| Video + ambience | LTX-2.5 22B nvfp4 | ComfyUI on :8199; Lanternist starts it if it's down |
| Stills motion, mix | ffmpeg with NVENC | subprocess |

Paths, URLs and render settings live in `lanternist.toml`; `lanternist.example.toml` lists every key.

The models don't fit on the 32 GB card together. Before each stage, Lanternist unloads Ollama and ComfyUI and waits until enough VRAM is free. The TTS and klein workers exit when they finish.

## How a film is made

- A storyboard is a single JSON document (`lanternist schema` prints its schema). Narration is in the story's language. Picture, motion and sound prompts are in English.
- The writer cuts each paragraph into one to three shots on its sentence boundaries, like a film editor: a wide shot, then a close-up. Shots of one paragraph cut straight to each other; paragraphs crossfade.
- Narration is recorded first. Each shot's picture holds exactly as long as its words.
- Every step is cached under a hash of its inputs, in `~/Lanternist/assets` and `~/Lanternist/steps`. A second render is instant. Editing one scene re-renders only that scene and the final mix.
- Consistency: each character's look, and the look of the objects and places the story returns to, is restated in every prompt that shows them. Each character is then drawn alone from the cast sheet, and every picture is drawn from the portraits of only who is in it, so nobody wanders into a scene they aren't in.
- The mix levels each video clip's own sound against the narration, then sets the whole film to −16 LUFS in two passes.

## Develop

```bash
scripts/check                               # every gate CI runs: format, lint, types, tests, build, duplication
uv run pytest                               # unit tests + the whole pipeline with fake engines
LANTERNIST_FAKE_ENGINES=1 uv run lanternist serve   # UI work without the GPU
LANTERNIST_FAKE_ENGINES=1 LANTERNIST_FAKE_PACE=1.5 uv run lanternist serve   # each fake item takes 1.5 s, to watch the progress
cd web && pnpm dev                          # Vite on :5173, proxying /api to :8420
```

`plans/MVP_PLAN.md` has the plan this was built from; `plans/M2_PLAN.md` is the one in progress. `CLAUDE.md` holds the
conventions every change follows.

Licences: FLUX.2 [klein] 9B is non-commercial, so it's for personal use. Qwen3-TTS and Ollama's Qwen models are Apache 2.0. LTX-2.5 is free under the LTX Community licence below $10M annual revenue.
