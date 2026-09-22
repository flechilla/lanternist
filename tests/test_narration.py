"""Narration on fal: each family's request, chunks joined exactly, cloned voices, and voice samples."""

import asyncio
import wave

import pytest

from lanternist import text, timing
from lanternist.db import Job
from lanternist.engines import catalog
from lanternist.engines.fal_tts import FalTts, VoiceError, join_speech
from lanternist.jobs import Runner
from lanternist.pipeline import Pipeline


def tts(cfg, model, voice, language="es") -> FalTts:
    eng = catalog.tts(cfg, None, model, voice, language)
    assert isinstance(eng, FalTts)
    return eng


@pytest.mark.parametrize(
    ("model", "voice", "voice_args", "expected"),
    [
        (
            "fal/elevenlabs-v3",
            "Aria",
            {},
            {
                "text": "Hola.",
                "voice": "Aria",
                "language_code": "es",
                "stability": 0.5,
                "apply_text_normalization": "auto",
            },
        ),
        (
            "fal/minimax-speech-2.8-hd",
            "Calm_Woman",
            {},
            {
                "prompt": "Hola.",
                "voice_setting": {"voice_id": "Calm_Woman", "speed": 1.0, "vol": 1.0, "pitch": 0},
                "language_boost": "Spanish",
                "output_format": "url",
                "audio_setting": {"format": "mp3", "sample_rate": 32000, "bitrate": 128000, "channel": 1},
            },
        ),
        (
            "fal/qwen-3-tts-1.7b",
            "Serena",
            {},
            {
                "text": "Hola.",
                "language": "Spanish",
                "voice": "Serena",
                "max_new_tokens": 4096,
                "temperature": 0.9,
                "top_k": 50,
                "top_p": 1.0,
                "repetition_penalty": 1.05,
            },
        ),
        (
            "fal/chatterbox-multilingual",
            "demo",
            {"clip_url": "https://cdn/demo.wav"},
            {
                "text": "Hola.",
                "voice": "https://cdn/demo.wav",
                "custom_audio_language": "spanish",
                "seed": 7,
                "exaggeration": 0.5,
                "temperature": 0.8,
                "cfg_scale": 0.5,
            },
        ),
    ],
)
def test_each_narration_family_sends_exactly_this(fake_cfg, model, voice, voice_args, expected):
    assert tts(fake_cfg, model, voice).arguments("Hola.", voice_args, 7) == expected


def test_a_cloned_qwen_voice_sends_its_embedding_and_transcript(fake_cfg, voices):
    (voices / "demo.txt").write_text("Esto es lo que digo.", encoding="utf-8")
    body = tts(fake_cfg, "fal/qwen-3-tts-1.7b", "demo").arguments("Hola.", {"embedding_url": "E"}, 7)
    assert (
        body["speaker_voice_embedding_file_url"] == "E" and body["reference_text"] == "Esto es lo que digo."
    )
    assert "voice" not in body


def test_voices_must_fit_the_model(fake_cfg):
    with pytest.raises(VoiceError, match="isn't one of ElevenLabs v3"):
        tts(fake_cfg, "fal/elevenlabs-v3", "demo")
    with pytest.raises(FileNotFoundError):
        tts(fake_cfg, "fal/chatterbox-multilingual", "nobody")


def test_chatterbox_chunks_stay_under_its_300_characters(fake_cfg):
    words = " ".join(["Una frase corta para contar un cuento."] * 30)
    assert max(len(c) for c in tts(fake_cfg, "fal/chatterbox-multilingual", "demo").chunks(words)) <= 300
    assert max(len(c) for c in text.tts_chunks(words, "es")) > 300  # the local limit is 350


def test_chunks_join_with_the_gap_and_keep_their_lengths(tmp_path):
    parts = []
    for k, seconds in enumerate([1.0, 0.5]):
        path = tmp_path / f"{k}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\1\0" * int(24000 * seconds))
        parts.append(path)
    out = tmp_path / "scene.wav"
    assert join_speech(parts, 0.25, out) == [1.0, 0.5]
    with wave.open(str(out)) as w:
        assert w.getnframes() == 24000 * 1.75


# ------------------------------------------------------------------------------------ a board on fal
def endpoints(fakes) -> list[str]:
    return [fakes.fal.requests[r].endpoint for r in fakes.fal.submits]


async def test_a_board_narrated_by_an_elevenlabs_preset(fake_cfg, db, fakes, make_story):
    sb = make_story(("still", "still"))
    sb.language, sb.models.tts, sb.voice = "es", "fal/elevenlabs-v3", "Aria"
    sb.scenes[0].narration[0].text = " ".join(["Una frase para leer en voz alta."] * 14)  # two chunks
    p = Pipeline(fake_cfg, db=db)
    narration = await p.narrate(sb)
    assert endpoints(fakes).count("fal-ai/elevenlabs/tts/eleven-v3") == 3
    first = narration[0]
    assert len(first.chunks) == 2 and len(first.chunk_durations) == 2
    assert first.duration == pytest.approx(sum(first.chunk_durations) + fake_cfg.render.chunk_gap)
    # The subtitle cues follow the chunks' real lengths, as they do for local narration.
    cues = timing.cues(
        [n.chunks for n in narration], [n.chunk_durations for n in narration], [0.5, 30.0], 0.25
    )
    assert cues[0].start == 0.5 and cues[-1].end == pytest.approx(30.0 + narration[1].duration)

    fakes.fal.submits.clear()
    assert await p.narrate(sb) == narration and not fakes.fal.submits  # all cached


async def test_a_cloned_voice_makes_its_embedding_once(fake_cfg, db, fakes, make_story):
    sb = make_story(("still", "still", "still"))
    sb.models.tts = "fal/qwen-3-tts-1.7b"
    p = Pipeline(fake_cfg, db=db)
    await p.narrate(sb)
    sb.scenes[1].narration[0].text = "A new line for the second scene."
    await p.narrate(sb)
    assert endpoints(fakes).count("fal-ai/qwen-3-tts/clone-voice/1.7b") == 1
    speaks = [
        fakes.fal.requests[r] for r in fakes.fal.submits if "text-to-speech" in fakes.fal.requests[r].endpoint
    ]
    assert len(speaks) == 4 and all(r.arguments["speaker_voice_embedding_file_url"] for r in speaks)


async def test_a_language_the_model_doesnt_speak_is_refused(fake_cfg, db, make_story):
    sb = make_story(("still",))
    sb.models.tts, sb.voice, sb.language = "fal/chatterbox-multilingual", "demo", "de"
    await Pipeline(fake_cfg, db=db).narrate(sb)  # German is one of Chatterbox's 23
    sb.language = "xx"
    with pytest.raises(ValueError, match="not supported by Chatterbox"):
        await Pipeline(fake_cfg, db=db).narrate(sb)


# ------------------------------------------------------------------------------------ voices and samples
def test_voice_samples_through_the_api(client, wait):
    cat = client.get("/api/voices/catalog", params={"tts": "fal/elevenlabs-v3", "language": "es"}).json()
    assert cat["speaks"] and not cat["clone"] and cat["recordings"] == []
    aria = next(v for v in cat["presets"] if v["id"] == "Aria")
    assert aria["sample"] is None and 0 < cat["sample_usd"] < 0.02  # about a hundred characters

    made = client.post(
        "/api/voices/sample", json={"tts": "fal/elevenlabs-v3", "voice": "Aria", "language": "es"}
    ).json()
    job = wait(made["job"]["id"])
    assert job["story_id"] is None and job["result"]["audio"].endswith(".wav")
    again = client.post(
        "/api/voices/sample", json={"tts": "fal/elevenlabs-v3", "voice": "Aria", "language": "es"}
    ).json()
    assert again == {"audio": job["result"]["audio"], "job": None}
    cat = client.get("/api/voices/catalog", params={"tts": "fal/elevenlabs-v3", "language": "es"}).json()
    assert next(v for v in cat["presets"] if v["id"] == "Aria")["sample"] == job["result"]["audio"]

    local = client.get("/api/voices/catalog", params={"language": "es"}).json()
    assert local["local"] and local["recordings"][0]["name"] == "demo" and local["sample_usd"] is None
    refused = client.post("/api/voices/sample", json={"voice": "demo", "language": "es"})
    assert refused.status_code == 422 and "listen to the recording itself" in refused.json()["detail"]
    assert (
        client.post("/api/voices/sample", json={"tts": "fal/elevenlabs-v3", "voice": "demo"}).status_code
        == 422
    )


async def test_a_sample_doesnt_wait_behind_a_render(cfg, db, until):
    runner = Runner(cfg, db)
    release = asyncio.Event()

    async def execute(job, progress):
        if job.kind == "render":
            await release.wait()  # a long render holds the queue
        return {"kind": job.kind}

    runner.execute = execute
    runner.start()
    try:
        with db.session() as s:
            s.add(Job(id="r1", story_id=None, kind="render", params={}, progress={}))
            s.commit()
        runner._wake(False)
        await until(lambda: runner.current is not None)
        sample = runner.enqueue(None, "sample", None, {"voice": "Aria"})
        await until(lambda: db.update_job(sample.id).status == "done")
        assert runner.current is not None and runner.current[0] == "r1"  # the render is still going
    finally:
        release.set()
        await runner.stop()
    assert db.update_job(sample.id).result == {"kind": "sample"}
