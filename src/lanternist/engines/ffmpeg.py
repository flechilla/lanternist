"""Everything ffmpeg does: stills with camera moves, normalised scene clips, and the final mix.

Every scene becomes its own normalised clip (target size, fps, yuv420p, stereo 48 kHz), exactly
as long as its slot plus crossfade handles. The mix then only crossfades clips and lays the
narration on top, so editing one scene re-encodes one clip and the mix.
"""

import asyncio
import json
import logging
import math
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import cast

from ..config import Render
from ..timing import Timeline

log = logging.getLogger(__name__)
SILENT = -70.0  # LUFS: where ebur128 stops measuring; a still's silent track reads as this
MAX_LIFT = 12.0  # dB: the most a faint clip's sound is raised toward the narration
MEASURING = 8  # loudness measurements at once; each decodes one file's sound
TRUE_PEAK = -1.5  # dBTP: headroom for the AAC encoder's overshoot
LOUDNESS_RANGE = 11  # LU: loudnorm's default, which narration sits well inside
SUB_STYLE = "FontName=Noto Sans,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=3,MarginV=36"


class FfmpegError(RuntimeError):
    pass


async def run(
    args: list[str], loglevel: str = "error", on_time: Callable[[float], None] | None = None
) -> str:
    """Run ffmpeg and return what it logged, which is nothing but errors unless `loglevel` asks for more.
    `on_time` hears how many seconds of output it has written, as it writes them."""
    progress = ["-progress", "pipe:1", "-nostats"] if on_time else []
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", loglevel, "-nostdin", "-y", *progress, *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE if on_time else subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        if on_time:
            errors = asyncio.ensure_future(cast(asyncio.StreamReader, proc.stderr).read())
            async for raw in cast(asyncio.StreamReader, proc.stdout):  # stdout=PIPE, so never None
                key, _, value = raw.decode(errors="replace").strip().partition("=")
                if key == "out_time_us" and value.isdigit():  # "N/A" until the first frame is out
                    on_time(int(value) / 1_000_000)
            err = await errors
            await proc.wait()
        else:
            _, err = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    log_text = err.decode(errors="replace")
    if proc.returncode != 0:
        raise FfmpegError(f"ffmpeg failed: {log_text[-2000:]}\ncmd: {' '.join(cmd)[:1500]}")
    return log_text


async def encode(build, r: Render, on_time: Callable[[float], None] | None = None) -> None:
    """Run an encode built by `build(render_settings)`; if the hardware encoder fails (it can't get a
    session or memory while a model fills the GPU), encode on the CPU instead."""
    try:
        await run(build(r), on_time=on_time)
    except FfmpegError as e:
        if r.encoder == "libx264":
            raise
        log.warning("%s failed, retrying with libx264: %s", r.encoder, str(e).splitlines()[0][:200])
        await run(build(r.model_copy(update={"encoder": "libx264"})), on_time=on_time)


def probe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data = json.loads(out)
    streams = data.get("streams", [])
    video: dict = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "video_duration": float(video.get("duration", 0) or 0),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": video.get("width"),
        "height": video.get("height"),
    }


def _venc(r: Render, final: bool) -> list[str]:
    if r.encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "medium" if final else "fast", "-crf", "18" if final else "16"]
    return ["-c:v", r.encoder, "-preset", "p5", "-b:v", r.bitrate if final else "24M"]


def camera_expr(camera: str, frames: int) -> tuple[str, str, str]:
    """zoompan (z, x, y). Oversampled 2x before zoompan, which steps in whole source pixels."""
    rate, top = 0.0004375, 1.12  # the prototype's 0.00035/frame at 30 fps, per frame at 24 fps
    centre = ("iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)")
    if camera == "push_in":
        return f"min(1+{rate}*on,{top})", *centre
    if camera == "pull_out":
        return f"max({top}-{rate}*on,1)", *centre
    if camera == "pan_right":
        return "1.1", f"(iw-iw/zoom)*on/{max(frames - 1, 1)}", centre[1]
    if camera == "pan_left":
        return "1.1", f"(iw-iw/zoom)*(1-on/{max(frames - 1, 1)})", centre[1]
    return "1", *centre


def resolve_camera(camera: str, index: int) -> str:
    # "auto" alternates direction per scene, so a run of stills doesn't feel identical.
    if camera == "auto":
        return "push_in" if index % 2 == 0 else "pull_out"
    return camera


async def still_clip(image: Path, length: float, camera: str, r: Render, out: Path) -> None:
    frames = max(round(length * r.fps), 2)
    z, x, y = camera_expr(camera, frames)
    w2, h2 = r.width * 2, r.height * 2
    vf = (
        f"scale={w2}:{h2}:force_original_aspect_ratio=increase:flags=lanczos,crop={w2}:{h2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={r.width}x{r.height}:fps={r.fps},"
        f"setsar=1,format=yuv420p"
    )
    await encode(
        lambda r: [
            "-i",
            str(image),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-filter_complex",
            f"[0:v]{vf}[v]",
            "-map",
            "[v]",
            "-map",
            "1:a",
            *_venc(r, final=False),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{length:.3f}",
            str(out),
        ],
        r,
    )


async def video_clip(src: Path, length: float, r: Render, out: Path) -> None:
    """Fit a generated clip to its slot: cover-scale, crop, conform fps; keep its ambience."""
    info = probe(src)
    vf = (
        f"[0:v]trim=0:{length:.3f},setpts=PTS-STARTPTS,"
        f"scale={r.width}:{r.height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={r.width}:{r.height},fps={r.fps},setsar=1,format=yuv420p,"
        f"tpad=stop_mode=clone:stop_duration={length:.3f}[v]"
    )
    fade_out = max(length - 0.3, 0)
    if info["has_audio"]:
        af = (
            f"[0:a]atrim=0:{length:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
            f"aformat=channel_layouts=stereo,afade=t=in:d=0.15,afade=t=out:st={fade_out:.3f}:d=0.3,apad[a]"
        )
        inputs = ["-i", str(src)]
    else:
        af = "[1:a]anull[a]"
        inputs = ["-i", str(src), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    await encode(
        lambda r: [
            *inputs,
            "-filter_complex",
            f"{vf};{af}",
            "-map",
            "[v]",
            "-map",
            "[a]",
            *_venc(r, final=False),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{length:.3f}",
            str(out),
        ],
        r,
    )


async def to_wav(src: Path, out: Path, rate: int) -> None:
    """Any speech file as mono 16-bit wav at `rate`, which the timeline measures to the sample."""
    await run(["-i", str(src), "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(out)])


async def thumbnail(src: Path, out: Path, width: int) -> None:
    """A picture as a JPEG `width` wide: what a vision model is shown."""
    await run(["-i", str(src), "-vf", f"scale={width}:-2", "-q:v", "4", str(out)])


async def last_frame(src: Path, out: Path) -> None:
    await run(["-sseof", "-0.25", "-i", str(src), "-update", "1", "-q:v", "2", str(out)])


async def concat(clips: list[Path], out: Path, faststart: bool = False) -> None:
    """Join shots end to end without re-encoding. `faststart` puts the index at the front, so the
    browser plays the file before it has all of it: fal's clips keep it at the end."""
    if len(clips) == 1 and not faststart:
        out.write_bytes(clips[0].read_bytes())
        return
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    index = ["-movflags", "+faststart"] if faststart else []
    await run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", *index, str(out)])


async def mux_audio(video: Path, sound: Path, out: Path) -> None:
    """A clip's own picture with another file's sound: the ambience made for it."""
    await run(
        [
            "-i",
            str(video),
            "-i",
            str(sound),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )


def ambience_gains(clips: list[float], narration: list[float]) -> list[float]:
    """dB that bring each clip's sound to the narration's loudness, so `ambience` puts every scene the
    same distance under the voice: a video model's sound bed swings by 30 dB from one clip to the
    next. A silent clip stays silent, and a faint one is lifted at most MAX_LIFT, not its noise with it."""
    voiced = [x for x in narration if x > SILENT]
    if not voiced:
        return [0.0] * len(clips)
    voice = 10 * math.log10(sum(10 ** (x / 10) for x in voiced) / len(voiced))
    return [0.0 if c <= SILENT else round(min(voice - c, MAX_LIFT), 2) for c in clips]


async def integrated(path: Path) -> float:
    """A file's integrated loudness in LUFS; SILENT when it has no sound."""
    report = await run(["-i", str(path), "-map", "0:a", "-af", "ebur128", "-f", "null", "-"], loglevel="info")
    found = re.findall(r"I:\s+(-?[\d.]+|-inf) LUFS", report)
    return max(float(found[-1]), SILENT) if found and found[-1] != "-inf" else SILENT


def audio_graph(tl: Timeline, r: Render, gains: list[float] | None = None) -> str:
    """The film's sound, before its loudness is set: each clip's ambience, levelled by `gains`, placed
    with its clip, the narration on top, and a fade out at the end, as [mixed]."""
    n = tl.n
    chains = []
    # Ambience: each clip's own sound, placed where its clip starts, ducked under the voice.
    for i in range(n):
        level = f"volume={gains[i]}dB," if gains and gains[i] else ""
        chains.append(f"[{i}:a]{level}adelay=delays={int(tl.clip_start(i) * 1000)}:all=1[a{i}]")
    amb = "".join(f"[a{i}]" for i in range(n))
    chains.append(
        f"{amb}amix=inputs={n}:normalize=0:duration=longest,volume={r.ambience}[amb]"
        if n > 1
        else f"{amb}volume={r.ambience}[amb]"
    )

    # Narration: every scene's wav at its speech start.
    for i in range(n):
        chains.append(
            f"[{n + i}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"adelay=delays={int(tl.speech_starts[i] * 1000)}:all=1[n{i}]"
        )
    nar = "".join(f"[n{i}]" for i in range(n))
    chains.append(
        (f"{nar}amix=inputs={n}:normalize=0:duration=longest" if n > 1 else f"{nar}anull")
        + f",apad=whole_dur={tl.total:.3f}[nar]"
    )
    chains.append(
        f"[nar][amb]amix=inputs=2:duration=first:normalize=0,"
        f"afade=t=out:st={max(tl.total - 1.2, 0):.3f}:d=1.2[mixed]"
    )
    return ";".join(chains)


def loudnorm(r: Render, measured: dict[str, str] | None = None) -> str:
    """ffmpeg's loudnorm at the film's target: measuring, or, given what the first pass measured,
    one linear gain for the whole film, so quiet pauses stay quiet instead of being pumped up."""
    target = f"loudnorm=I={r.loudness}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}"
    if measured is None:
        return f"{target}:print_format=json"
    return (
        f"{target}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true,aresample=48000"
    )


def mix_graph(
    tl: Timeline,
    r: Render,
    subtitles: Path | None,
    gains: list[float] | None = None,
    measured: dict[str, str] | None = None,
) -> str:
    n = tl.n
    # Video: crossfades centred on the scene boundaries, and straight cuts between the shots of a
    # paragraph. A cut is a concat, not a zero-length crossfade, which ends the video there; and
    # xfade takes only inputs on one timebase, which a concat's output is not until every clip is.
    chains = [f"[{i}:v]settb=AVTB[v{i}]" for i in range(n)]
    last = "v0"
    for i in range(1, n):
        if i in tl.cuts:
            chains.append(f"[{last}][v{i}]concat=n=2:v=1:a=0[x{i}]")
        else:
            chains.append(
                f"[{last}][v{i}]xfade=transition=fade:duration={tl.xfade}:offset={tl.clip_start(i):.3f}[x{i}]"
            )
        last = f"x{i}"
    vf = f"fade=t=in:d=1,fade=t=out:st={max(tl.total - 1.2, 0):.3f}:d=1.2"
    if subtitles:
        vf += f",subtitles=filename='{subtitles}':force_style='{SUB_STYLE}'"
    chains.append(f"[{last}]{vf},format=yuv420p[vout]")
    chains.append(audio_graph(tl, r, gains))
    chains.append(f"[mixed]{loudnorm(r, measured)}[aout]")
    return ";".join(chains)


async def loudness(inputs: list[str], tl: Timeline, r: Render, gains: list[float]) -> dict[str, str]:
    """The first loudnorm pass: how loud the film's sound is, as the second pass wants it told."""
    report = await run(
        [
            *inputs,
            "-filter_complex",
            f"{audio_graph(tl, r, gains)};[mixed]{loudnorm(r)}[m]",
            "-map",
            "[m]",
            "-f",
            "null",
            "-",
        ],
        loglevel="info",
    )
    found = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", report)
    if found is None:
        raise FfmpegError(f"ffmpeg's loudnorm didn't report the film's loudness: {report[-500:]}")
    return json.loads(found.group(0))


async def mix(
    clips: list[Path],
    wavs: list[Path],
    tl: Timeline,
    r: Render,
    out: Path,
    subtitles: Path | None = None,
    on_time: Callable[[float], None] | None = None,
) -> None:
    """The film: each clip's sound levelled against the narration, then the whole encoded at the target
    loudness. `on_time` hears how far the encode has got, in seconds of film."""
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    for w in wavs:
        inputs += ["-i", str(w)]
    sem = asyncio.Semaphore(MEASURING)

    async def measure(path: Path) -> float:
        async with sem:
            return await integrated(path)

    levels = await asyncio.gather(*(measure(f) for f in [*clips, *wavs]))
    gains = ambience_gains(levels[: len(clips)], levels[len(clips) :])
    measured = await loudness(inputs, tl, r, gains)
    await encode(
        lambda r: [
            *inputs,
            "-filter_complex",
            mix_graph(tl, r, subtitles, gains, measured),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *_venc(r, final=True),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{tl.total:.3f}",
            "-movflags",
            "+faststart",
            str(out),
        ],
        r,
        on_time,
    )
