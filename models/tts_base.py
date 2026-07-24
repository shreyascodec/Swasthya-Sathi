"""Shared TTS adapter contract for Stage [7] Voice.

A TTS adapter turns text into speech audio in the patient language. It returns
WAV bytes plus timing (duration) — the STAGE writes the file, so adapters stay
filesystem-free (same split as the OCR adapters). Timing is the seam a later
Wav2Lip avatar attaches to (ARCHITECTURE: audio->video seam).

Same ModelManager lifecycle as every model (load/unload frees VRAM).
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

from core.env import EnvProfile


class TTSUnavailable(ImportError):
    """Raised when a TTS runtime is missing."""


@dataclass
class Audio:
    data: bytes            # a complete WAV container
    sample_rate: int
    duration_ms: int
    lang: str


class TTSAdapterBase:
    default_vram_mb: int = 700    # FastPitch + HiFiGAN ballpark

    def __init__(self, logical_name: str, spec: dict, env: EnvProfile) -> None:
        self.logical_name = logical_name
        self.spec = spec
        self.env = env
        self.device: str = spec.get("device", env.device)
        self.is_gpu: bool = self.device.startswith("cuda")
        self._vram_mb: int = int(spec.get("vram_mb", self.default_vram_mb))
        self.sample_rate: int = int(spec.get("sample_rate", 22050))
        self._handle = None

    def load(self) -> None:
        if self._handle is None:
            self._handle = self._build()

    def unload(self) -> None:
        self._handle = None

    def vram_mb(self) -> int:
        return self._vram_mb if self.is_gpu else 0

    def synthesize(self, text: str, lang: str = "hi") -> Audio:
        self.load()
        return self._synthesize(text, lang)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def pcm_to_wav(pcm: bytes, sample_rate: int, tail_ms: int = 300) -> bytes:
        """Wrap PCM as a WAV, padding a short silence tail.

        VITS ends a long utterance right on the final sample — measured across
        sessions, the longest intake question consistently finished with 0.03 s
        of trailing silence while shorter ones kept 0.2-0.4 s. Played back that
        reads as the question being cut off mid-word. The pad costs a few KB and
        guarantees the last syllable is fully audible.
        """
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)          # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
            if tail_ms > 0:
                wf.writeframes(b"\x00\x00" * int(sample_rate * tail_ms / 1000))
        return buf.getvalue()

    # -- to implement -----------------------------------------------------
    def _build(self):  # pragma: no cover - runtime specific
        return None

    def _synthesize(self, text: str, lang: str) -> Audio:  # pragma: no cover
        raise NotImplementedError
