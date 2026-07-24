"""Kokoro-82M TTS adapter (Hindi) — Stage [7] Voice.

Kokoro is a compact (~82 M) StyleTTS2-family voice that runs realtime on CPU and
— crucially for us — is **Apache-2.0, including its Hindi voices**. That makes it
the commercial-clean Hindi engine we were missing: Piper's *engine* is MIT, but
every off-the-shelf Piper Hindi voice is CC-BY-NC-SA / IIT-M (non-commercial —
the same blocker as MMS). Kokoro fixes that at the same edge profile (RTF ~0.02-
0.03 warm, ~330 MB), and a native-speaker listen on our intake set passed. Full
licence trail + benchmark: `commercial.md` §0, `record.md` §9.

Provision via config:

    tts.primary:
      impl: kokoro
      lang_code: h          # Kokoro language code — 'h' = Hindi
      voice: hf_alpha       # hf_alpha/hf_beta (F), hm_omega/hm_psi (M)
      device: cpu           # GPU-free keeps Orin's budget for the LLM + STT
      sample_rate: 24000    # Kokoro native

Heavy deps (`kokoro`, `misaki`) import lazily on load; if absent this raises
``TTSUnavailable`` and the voice stage falls back to the silent stub. Setup:
`pip install kokoro soundfile`. First load downloads the weights from HF into the
HF cache; for the offline kiosk that cache ships on-device (same as every model).
"""

from __future__ import annotations

import numpy as np

from core.model_manager import register_adapter
from models.tts_base import Audio, TTSAdapterBase, TTSUnavailable

_REPO = "hexgrad/Kokoro-82M"


class KokoroTTSAdapter(TTSAdapterBase):
    default_vram_mb = 0  # CPU by default — no GPU footprint

    def _build(self):
        try:
            from kokoro import KPipeline
        except ImportError as exc:  # pragma: no cover - env dependent
            raise TTSUnavailable(
                "Kokoro not installed. `pip install kokoro soundfile`, or the "
                "voice stage falls back to the stub for Hindi."
            ) from exc

        lang_code = self.spec.get("lang_code", "h")   # 'h' = Hindi
        device = self.spec.get("device", "cpu")
        try:  # pragma: no cover - runtime specific
            # device kwarg lets us pin CPU (GPU-free); older builds infer it.
            try:
                pipe = KPipeline(lang_code=lang_code, repo_id=_REPO, device=device)
            except TypeError:
                pipe = KPipeline(lang_code=lang_code, repo_id=_REPO)
        except Exception as exc:  # noqa: BLE001
            raise TTSUnavailable(f"Kokoro load failed: {exc}") from exc
        return {"pipe": pipe, "voice": self.spec.get("voice", "hf_alpha")}

    def _synthesize(self, text: str, lang: str) -> Audio:  # pragma: no cover
        pipe = self._handle["pipe"]
        voice = self._handle["voice"]
        sr = int(self.spec.get("sample_rate", 24000))

        # KPipeline yields (graphemes, phonemes, audio) chunks; concat the audio.
        parts = [np.asarray(chunk[2], dtype=np.float32) for chunk in pipe(text, voice=voice)]
        audio = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)

        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        self.sample_rate = sr
        duration_ms = int(len(pcm) / 2 / sr * 1000)
        return Audio(data=self.pcm_to_wav(pcm, sr), sample_rate=sr,
                     duration_ms=duration_ms, lang=lang)


register_adapter(
    "kokoro",
    lambda logical_name, spec, env: KokoroTTSAdapter(logical_name, spec, env),
)
