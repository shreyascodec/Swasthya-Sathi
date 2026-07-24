"""Stub TTS — the config-swappable no-deps fallback for Stage [7].

Not a real vocoder. It synthesizes a VALID silent WAV whose duration is estimated
from the text length, so the whole voice flow — artifact saving + the AudioClip
timing seam for the future Wav2Lip avatar — runs end-to-end without the AI4Bharat
stack installed. Swap to the real voice by setting tts.primary.impl to
'ai4bharat-indic-tts'.
"""

from __future__ import annotations

from core.model_manager import register_adapter
from models.tts_base import Audio, TTSAdapterBase

# Rough speaking pace for the duration estimate (a clinician-readback cadence).
_MS_PER_CHAR = 55
_BASE_MS = 350
_MAX_MS = 30_000


class StubTTSAdapter(TTSAdapterBase):
    default_vram_mb = 0

    def _build(self):
        return {"stub": True}

    def _synthesize(self, text: str, lang: str) -> Audio:
        chars = len((text or "").strip())
        duration_ms = min(_MAX_MS, _BASE_MS + chars * _MS_PER_CHAR) if chars else _BASE_MS
        n_samples = int(self.sample_rate * duration_ms / 1000)
        pcm = b"\x00\x00" * n_samples          # 16-bit silence of the right length
        return Audio(data=self.pcm_to_wav(pcm, self.sample_rate),
                     sample_rate=self.sample_rate, duration_ms=duration_ms, lang=lang)


register_adapter("stub_tts", lambda logical_name, spec, env: StubTTSAdapter(logical_name, spec, env))
