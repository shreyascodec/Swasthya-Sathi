"""Startup model warmup — pay the cold-load cost before the first patient.

The pipeline loads each model lazily on first use, so on a fresh kiosk the FIRST
report eats every model's cold start — most visibly the ~80 s Kokoro TTS weight
load. This module loads models at boot instead, on a background thread, and
publishes readiness so the UI can show "warming up" and hold the Process button
until the box is actually ready.

Policy-aware by construction: it drives ``ModelManager.get()``/``release()``,
which already enforce the env's ``max_resident_gpu_models`` budget (1 on the
8 GB laptop). CPU-resident models (Kokoro ``tts``/``tts_en``, Vaani ``stt``) are
kept loaded because they cost nothing against the single GPU slot and are the
real cold-start pain; GPU models are *touched then released* — enough to warm the
OS page cache and prove the weights load, without pinning the one GPU slot that
the pipeline needs free for its first stage.

Best-effort: a model that fails to load (Ollama down, weights missing) is logged
and marked unavailable in readiness — the server never crashes because of it. The
pipeline still surfaces the real error at stage time exactly as before.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("swasthya.warmup")

# Logical models the 9-stage pipeline actually uses, in a sensible warm order
# (cheap CPU first so readiness reflects the expensive bits last). Intersected
# with the active config so an env that omits one just skips it.
PIPELINE_MODELS = ["tts", "tts_en", "stt", "ocr", "image_tag", "llm"]


def new_readiness() -> dict[str, Any]:
    return {"ready": False, "warming": False, "loaded": [], "unavailable": [], "seconds": None}


def run_warmup(pipeline, lock: threading.Lock, readiness: dict, models: list[str] | None = None) -> None:
    """Warm models into memory. Runs on a daemon thread; mutates ``readiness``.

    ``lock`` is the shared pipeline lock — held per model so a real request that
    arrives mid-warmup is serialized against it (single GPU, single worker).
    """
    names = [m for m in (models or PIPELINE_MODELS) if m in pipeline.config.models]
    t0 = time.time()
    readiness.update(ready=False, warming=True, seconds=None)
    log.info("warmup starting: %s", names)

    for name in names:
        with lock:
            try:
                adapter = pipeline.models.get(name)
                if getattr(adapter, "is_gpu", False):
                    # Don't pin the single GPU slot; weights are now warm on disk.
                    pipeline.models.release(name)
                    readiness["loaded"].append(f"{name} (touched)")
                else:
                    readiness["loaded"].append(name)  # CPU: keep resident
                log.info("warmed %s", name)
            except Exception as e:  # noqa: BLE001 — warmup is best-effort by design
                readiness["unavailable"].append(name)
                log.warning("warmup skipped %s: %s: %s", name, type(e).__name__, e)

    readiness.update(ready=True, warming=False, seconds=round(time.time() - t0, 1))
    log.info(
        "warmup done in %ss — resident=%s unavailable=%s",
        readiness["seconds"], readiness["loaded"], readiness["unavailable"],
    )


def start_warmup_thread(pipeline, lock: threading.Lock, readiness: dict) -> threading.Thread:
    t = threading.Thread(
        target=run_warmup, args=(pipeline, lock, readiness),
        name="warmup", daemon=True,
    )
    t.start()
    return t
