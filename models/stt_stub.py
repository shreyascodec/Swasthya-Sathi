"""Stub STT — the config-swappable no-deps fallback for answer capture.

Not a real recognizer. It sources a transcript from a sidecar
``<audio_path>.txt`` (the "spoken" answer) when present; otherwise returns an
empty transcript rather than inventing words. Lets the Q&A capture flow +
ModelManager seam run end-to-end without faster-whisper installed.

Swap to the real engine by setting stt.primary.impl to 'faster-whisper'.
"""

from __future__ import annotations

from pathlib import Path

from core.model_manager import register_adapter
from models.stt_base import STTAdapterBase, Transcript


class StubSTTAdapter(STTAdapterBase):
    default_vram_mb = 0

    def _build(self):
        return {"stub": True}

    def _transcribe(self, audio_path: str, lang: str) -> Transcript:
        sidecar = Path(str(audio_path) + ".txt")
        if sidecar.exists():
            return Transcript(text=sidecar.read_text(encoding="utf-8").strip(),
                              lang=lang, confidence=0.99)
        return Transcript(text="", lang=lang, confidence=0.0)


register_adapter("stub_stt", lambda logical_name, spec, env: StubSTTAdapter(logical_name, spec, env))
