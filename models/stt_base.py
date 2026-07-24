"""Shared STT (speech-to-text) adapter contract for Stage [6] answer capture.

An STT adapter transcribes a recorded answer clip to text in the patient
language. Same ModelManager lifecycle as every other model (load/unload so VRAM
frees). Concrete adapters: faster-whisper (primary), a stub for tests/no-deps,
and later an Indic-conformer for Indian languages.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.env import EnvProfile


class STTUnavailable(ImportError):
    """Raised when an STT runtime is missing or unreachable."""


@dataclass
class Transcript:
    text: str = ""
    lang: str = "hi"
    confidence: float | None = None


class STTAdapterBase:
    default_vram_mb: int = 500     # faster-whisper small INT8 ballpark

    def __init__(self, logical_name: str, spec: dict, env: EnvProfile) -> None:
        self.logical_name = logical_name
        self.spec = spec
        self.env = env
        self.device: str = spec.get("device", "cpu")   # whisper-small runs fine on CPU
        self.is_gpu: bool = self.device.startswith("cuda")
        self._vram_mb: int = int(spec.get("vram_mb", self.default_vram_mb))
        self._handle = None

    def load(self) -> None:
        if self._handle is None:
            self._handle = self._build()

    def unload(self) -> None:
        self._handle = None

    def vram_mb(self) -> int:
        return self._vram_mb if self.is_gpu else 0

    def transcribe(self, audio_path: str, lang: str = "hi") -> Transcript:
        self.load()
        return self._transcribe(audio_path, lang)

    # -- to implement -----------------------------------------------------
    def _build(self):  # pragma: no cover - runtime specific
        return None

    def _transcribe(self, audio_path: str, lang: str) -> Transcript:  # pragma: no cover
        raise NotImplementedError
