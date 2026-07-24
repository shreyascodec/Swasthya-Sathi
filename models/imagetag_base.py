"""Shared image-tagging adapter contract + output type.

A tagger returns ONLY a clinical-image *type* (skin/eye/wound/oral) and a
confidence score. It never emits a diagnosis (product invariant). Quality is a
separate flag, reused from the Phase-1 gate — not decided by the model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.env import EnvProfile

DEFAULT_CLASSES = ["skin", "eye", "wound", "oral"]


@dataclass
class TagResult:
    type: str = "unknown"     # one of the configured classes, or "unknown"
    score: float = 0.0        # classifier confidence for `type`


class ImageTagAdapterBase:
    """Base tagger adapter implementing the ModelManager lifecycle contract."""

    default_vram_mb: int = 200

    def __init__(self, logical_name: str, spec: dict, env: EnvProfile) -> None:
        self.logical_name = logical_name
        self.spec = spec
        self.env = env
        self.device: str = spec.get("device", env.device)
        self.is_gpu: bool = self.device.startswith("cuda")
        self._vram_mb: int = int(spec.get("vram_mb", self.default_vram_mb))
        self.classes: list[str] = list(spec.get("classes", DEFAULT_CLASSES))
        self._model = None

    def load(self) -> None:
        if self._model is None:
            self._model = self._build_model()

    def unload(self) -> None:
        self._model = None

    def vram_mb(self) -> int:
        return self._vram_mb if self.is_gpu else 0

    def classify(self, image: np.ndarray | None, source_path: str | None = None) -> TagResult:
        self.load()
        return self._classify(image, source_path)

    # -- to implement in subclasses --------------------------------------
    def _build_model(self):  # pragma: no cover - engine specific
        return None

    def _classify(self, image: np.ndarray | None, source_path: str | None) -> TagResult:  # pragma: no cover
        raise NotImplementedError
