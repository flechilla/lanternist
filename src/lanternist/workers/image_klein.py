"""FLUX.2 [klein] 9B picture worker. Runs INSIDE a venv with a diffusers that has Flux2KleinPipeline.

Job:
    {"weights": path, "steps": 4, "guidance": 1.0,
     "items": [{"id": "cast", "prompt": "...", "seed": 7, "width": 1024, "height": 1024,
                "refs": [], "out": "/.../cast.png"}, ...]}

Items run in order, so a cast sheet rendered first can be the reference of the keyframes after
it. klein is step-distilled: the model card asks for 4 steps at guidance 1.0, and raising either
makes it worse. Its 35 GB of weights need CPU offload on a 32 GB card.
"""

import json
import os
import sys
import time
import traceback

os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")


def emit(**event):
    print("@@LX " + json.dumps(event, ensure_ascii=False), flush=True)


def main():
    with open(sys.argv[1], encoding="utf-8") as f:
        job = json.load(f)

    import torch
    from diffusers import Flux2KleinPipeline
    from PIL import Image

    t0 = time.time()
    pipe = Flux2KleinPipeline.from_pretrained(job["weights"], torch_dtype=torch.bfloat16)
    pipe.enable_model_cpu_offload()
    pipe.vae.enable_tiling()
    emit(event="loaded", secs=round(time.time() - t0, 1))

    for item in job["items"]:
        t = time.time()
        refs = [Image.open(r).convert("RGB") for r in item.get("refs", [])]
        image = pipe(
            prompt=item["prompt"],
            image=refs or None,
            width=item["width"],
            height=item["height"],
            num_inference_steps=job.get("steps", 4),
            guidance_scale=job.get("guidance", 1.0),
            generator=torch.Generator("cuda").manual_seed(item["seed"]),
        ).images[0]
        image.save(item["out"])
        emit(
            event="item",
            id=item["id"],
            out=item["out"],
            width=image.width,
            height=image.height,
            secs=round(time.time() - t, 1),
        )

    emit(event="done", peak_vram_gb=round(torch.cuda.max_memory_allocated() / 1e9, 1))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        emit(event="error", message=traceback.format_exc()[-2000:])
        sys.exit(1)
