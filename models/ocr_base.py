"""Shared OCR adapter contract + output types.

Every OCR engine (PaddleOCR, Surya, stub) is a ModelManager adapter that
returns the same ``OCRPage`` shape, so the field-extraction layer and the stage
are engine-agnostic and engines are swappable purely from config.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core.env import EnvProfile


@dataclass
class OCRToken:
    text: str
    confidence: float = 1.0
    bbox: tuple[int, int, int, int] | None = None   # x, y, w, h


@dataclass
class OCRPage:
    text: str = ""
    tokens: list[OCRToken] = field(default_factory=list)

    @property
    def mean_confidence(self) -> float:
        if not self.tokens:
            return 1.0
        return sum(t.confidence for t in self.tokens) / len(self.tokens)


class OCRAdapterBase:
    """Base adapter: implements the ModelManager lifecycle contract.

    Subclasses implement ``_build_engine`` (lazy import of the real engine) and
    ``_recognize`` (engine-specific inference -> OCRPage).
    """

    #: default footprint estimate (MB) if not given in config; per-engine override
    default_vram_mb: int = 1024

    def __init__(self, logical_name: str, spec: dict, env: EnvProfile) -> None:
        self.logical_name = logical_name
        self.spec = spec
        self.env = env
        self.device: str = spec.get("device", env.device)
        self.is_gpu: bool = self.device.startswith("cuda")
        self._vram_mb: int = int(spec.get("vram_mb", self.default_vram_mb))
        self._engine = None

    # -- ModelManager contract -------------------------------------------
    def load(self) -> None:
        if self._engine is None:
            self._engine = self._build_engine()

    def unload(self) -> None:
        self._engine = None  # drop reference; ModelManager empties CUDA cache

    def vram_mb(self) -> int:
        return self._vram_mb if self.is_gpu else 0

    # -- inference --------------------------------------------------------
    def recognize(self, image: np.ndarray | None, source_path: str | None = None) -> OCRPage:
        self.load()
        return self._recognize(image, source_path)

    def recognize_batch(
        self,
        images: list[np.ndarray | None],
        source_paths: list[str | None] | None = None,
    ) -> list[OCRPage]:
        """Recognize many pages in one call. Default loops ``recognize``;
        engines with real batch inference (PaddleOCR) override ``_recognize_batch``."""
        self.load()
        paths = source_paths or [None] * len(images)
        return self._recognize_batch(images, paths)

    def _recognize_batch(
        self, images: list[np.ndarray | None], source_paths: list[str | None]
    ) -> list[OCRPage]:
        return [self._recognize(im, sp) for im, sp in zip(images, source_paths)]

    # -- to implement in subclasses --------------------------------------
    def _build_engine(self):  # pragma: no cover - engine specific
        return None

    def _recognize(self, image: np.ndarray | None, source_path: str | None) -> OCRPage:  # pragma: no cover
        raise NotImplementedError
