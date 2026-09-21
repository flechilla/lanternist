"""Qwen3-TTS 1.7B narration worker. Runs INSIDE the qwen3tts venv: stdlib + that venv only.

Job:
    {"weights": path, "ref_audio": wav, "ref_text": str|null, "language": "Spanish",
     "chunk_gap": 0.25,
     "items": [{"id": "s01", "chunks": ["...", "..."], "seed": 8, "out": "/.../s01.wav"}]}

Emits one 'item' event per scene with the real duration of every chunk, which is what the
timeline and the subtitle cues are built from.
"""

import json
import os
import sys
import time
import traceback

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def emit(**event):
    print("@@LX " + json.dumps(event, ensure_ascii=False), flush=True)


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    t0 = time.time()
    model = Qwen3TTSModel.from_pretrained(job["weights"], device_map="cuda:0", dtype=torch.bfloat16)
    ref_text = job.get("ref_text")
    # Building the clone prompt once keeps the reference encode out of the per-chunk loop.
    prompt = model.create_voice_clone_prompt(ref_audio=job["ref_audio"], ref_text=ref_text,
                                             x_vector_only_mode=ref_text is None)
    emit(event="loaded", secs=round(time.time() - t0, 1))

    for item in job["items"]:
        t = time.time()
        torch.manual_seed(item.get("seed", 0))
        clips, sr = [], 24000
        for text in item["chunks"]:
            wavs, sr = model.generate_voice_clone(text=text, language=job["language"],
                                                  voice_clone_prompt=prompt)
            clips.append(np.asarray(wavs[0], dtype=np.float32).reshape(-1))
        gap = np.zeros(int(sr * job.get("chunk_gap", 0.25)), dtype=np.float32)
        parts = []
        for k, clip in enumerate(clips):
            if k:
                parts.append(gap)
            parts.append(clip)
        audio = np.concatenate(parts)
        sf.write(item["out"], audio, sr)
        emit(event="item", id=item["id"], out=item["out"], sample_rate=sr,
             duration=round(len(audio) / sr, 3),
             chunk_durations=[round(len(c) / sr, 3) for c in clips],
             secs=round(time.time() - t, 1))

    emit(event="done", peak_vram_gb=round(torch.cuda.max_memory_allocated() / 1e9, 1))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        emit(event="error", message=traceback.format_exc()[-2000:])
        sys.exit(1)
