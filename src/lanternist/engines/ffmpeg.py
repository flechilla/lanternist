"""Everything ffmpeg does: stills with camera moves, normalised scene clips, and the final mix.

Every scene becomes its own normalised clip (target size, fps, yuv420p, stereo 48 kHz), exactly
as long as its slot plus crossfade handles. The mix then only crossfades clips and lays the
narration on top, so editing one scene re-encodes one clip and the mix.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path

from ..config import Render
from ..timing import Timeline

log = logging.getLogger(__name__)
SUB_STYLE = "FontName=Noto Sans,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=3,MarginV=36"


class FfmpegError(RuntimeError):
    pass


async def run(args: list[str]) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        _, err = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode != 0:
        raise FfmpegError(
            f"ffmpeg failed: {err.decode(errors='replace')[-2000:]}\ncmd: {' '.join(cmd)[:1500]}"
        )


async def encode(build, r: Render) -> None:
    """Run an encode built by `build(render_settings)`; if the hardware encoder fails (it can't get a
    session or memory while a model fills the GPU), encode on the CPU instead."""
    try:
        await run(build(r))
    except FfmpegError as e:
        if r.encoder == "libx264":
            raise
        log.warning("%s failed, retrying with libx264: %s", r.encoder, str(e).splitlines()[0][:200])
        await run(build(r.model_copy(update={"encoder": "libx264"})))


def probe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
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


async def last_frame(src: Path, out: Path) -> None:
    await run(["-sseof", "-0.25", "-i", str(src), "-update", "1", "-q:v", "2", str(out)])


async def concat(clips: list[Path], out: Path) -> None:
    if len(clips) == 1:
        out.write_bytes(clips[0].read_bytes())
        return
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{c}'\n" for c in clips))
    await run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])


def mix_graph(tl: Timeline, r: Render, subtitles: Path | None) -> str:
    n = tl.n
    chains = []
    # Video: crossfades centred on the scene boundaries.
    last = "0:v"
    for i in range(1, n):
        offset = tl.bounds[i] - tl.xfade / 2
        chains.append(f"[{last}][{i}:v]xfade=transition=fade:duration={tl.xfade}:offset={offset:.3f}[x{i}]")
        last = f"x{i}"
    vf = f"fade=t=in:d=1,fade=t=out:st={max(tl.total - 1.2, 0):.3f}:d=1.2"
    if subtitles:
        vf += f",subtitles=filename='{subtitles}':force_style='{SUB_STYLE}'"
    chains.append(f"[{last}]{vf},format=yuv420p[vout]")

    # Ambience: each clip's own sound, placed where its clip starts, ducked under the voice.
    for i in range(n):
        chains.append(f"[{i}:a]adelay=delays={int(tl.clip_start(i) * 1000)}:all=1[a{i}]")
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
        f"afade=t=out:st={max(tl.total - 1.2, 0):.3f}:d=1.2[aout]"
    )
    return ";".join(chains)


async def mix(
    clips: list[Path], wavs: list[Path], tl: Timeline, r: Render, out: Path, subtitles: Path | None = None
) -> None:
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    for w in wavs:
        inputs += ["-i", str(w)]
    await encode(
        lambda r: [
            *inputs,
            "-filter_complex",
            mix_graph(tl, r, subtitles),
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
    )
