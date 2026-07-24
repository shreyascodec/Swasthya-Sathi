"""Stub image tagger — the config-swappable no-deps fallback.

Not a trained classifier. It sources a tag from a sidecar
``<source_path>.tag.json`` (``{"type": "skin", "score": 0.9}``) when present —
used by tests and canned demos. With no sidecar it returns ``unknown`` rather
than guessing, keeping the POC honest (no fabricated clinical labels).

Swap to the real model by setting image_tag.primary.impl to 'mobilenetv3'.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from core.model_manager import register_adapter
from models.imagetag_base import ImageTagAdapterBase, TagResult


class StubImageTagAdapter(ImageTagAdapterBase):
    default_vram_mb = 0

    def _build_model(self):
        return {"stub": True}

    def _classify(self, image: np.ndarray | None, source_path: str | None) -> TagResult:
        if source_path:
            sidecar = Path(str(source_path) + ".tag.json")
            if sidecar.exists():
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                return TagResult(
                    type=str(data.get("type", "unknown")),
                    score=float(data.get("score", 0.0)),
                )
        return TagResult("unknown", 0.0)


register_adapter("stub_imagetag", lambda logical_name, spec, env: StubImageTagAdapter(logical_name, spec, env))
