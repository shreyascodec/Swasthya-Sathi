"""Piper TTS adapter (English) — Stage [7] Voice.

Piper is a compact VITS/ONNX voice (~15M params) that runs REALTIME on CPU,
including ARM/aarch64 (Raspberry Pi / Jetson) — it uses zero GPU, which on the
Orin kiosk keeps the whole 12 GB budget free for the LLM + STT. Voices are
permissively licensed (MIT/CC), so it's a commercial-clean replacement for
MMS-TTS on the English path (IndicF5 covers only Indian languages).

Provision via config:

    tts_en.primary:
      impl: piper
      voice: models/weights/piper/en_US-lessac-medium.onnx   # + .onnx.json beside it
      device: cpu

Heavy deps (piper) are imported lazily on load; if piper or the voice model is
absent this raises ``TTSUnavailable`` and the voice stage falls back (MMS today,
stub as a floor). Setup: `pip install piper-tts`, download an English voice
(.onnx + .onnx.json) into ``voice`` — no runtime download (offline-first).
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

from core.model_manager import register_adapter
from models.tts_base import Audio, TTSAdapterBase, TTSUnavailable


class PiperTTSAdapter(TTSAdapterBase):
    default_vram_mb = 0  # CPU only — no GPU footprint (the whole point)

    def _build(self):
        try:
            from piper import PiperVoice
        except ImportError as exc:  # pragma: no cover - env dependent
            raise TTSUnavailable(
                "Piper not installed. `pip install piper-tts`, or the voice "
                "stage falls back to MMS/stub for English."
            ) from exc

        voice_path = self.spec.get("voice")
        if not voice_path or not Path(voice_path).exists():
            raise TTSUnavailable(
                "Piper needs a voice model — set tts_en.voice to a local .onnx "
                "(with its .onnx.json beside it). No runtime download "
                "(offline-first). Falling back until provisioned."
            )
        try:  # pragma: no cover - runtime specific
            voice = PiperVoice.load(voice_path)
        except Exception as exc:  # noqa: BLE001
            raise TTSUnavailable(f"Piper voice load failed: {exc}") from exc
        return {"voice": voice}

    def _synthesize(self, text: str, lang: str) -> Audio:  # pragma: no cover
        voice = self._handle["voice"]
        # Piper writes a full WAV to a file-like; capture it, then read back the
        # PCM so we can re-wrap with the base's silence-tail padding.
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(text, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as rf:
            sr = rf.getframerate()
            pcm = rf.readframes(rf.getnframes())
        self.sample_rate = sr
        duration_ms = int(len(pcm) / 2 / sr * 1000)
        return Audio(data=self.pcm_to_wav(pcm, sr), sample_rate=sr,
                     duration_ms=duration_ms, lang=lang)


register_adapter(
    "piper",
    lambda logical_name, spec, env: PiperTTSAdapter(logical_name, spec, env),
)
