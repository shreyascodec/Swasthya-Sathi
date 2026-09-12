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
      device: cuda          # measured RTF 0.024 vs 0.351 on 16 CPU threads
      sample_rate: 24000    # Kokoro native
      pinned: true          # 330 MB; never evicted by the GPU-count policy
      keep_warm: true       # the voice stage skips its release

``device: cpu`` still works unchanged and stays the right choice on a box with no
CUDA or with the card fully committed — it costs ~0.35 s of synthesis per second
of speech instead of ~0.024 s.

Heavy deps (`kokoro`, `misaki`) import lazily on load; if absent this raises
``TTSUnavailable`` and the voice stage falls back to the silent stub. Setup:
`pip install kokoro soundfile`. First load downloads the weights from HF into the
HF cache; for the offline kiosk that cache ships on-device (same as every model).
"""

from __future__ import annotations

import numpy as np

from core.model_manager import register_adapter
from models.tts_base import Audio, TTSAdapterBase, TTSUnavailable, phoneme_timeline, token_timeline

_REPO = "hexgrad/Kokoro-82M"


class KokoroTTSAdapter(TTSAdapterBase):
    default_vram_mb = 400  # 82 M params; ~330 MB resident on the 4060

    warm_text = "नमस्ते"   # Hindi, so warm() touches the misaki Devanagari G2P

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

    def synthesize_aligned(self, text: str, lang: str = "hi"):  # pragma: no cover
        """Same synthesis, but keep the ``phonemes`` half of each KPipeline chunk
        (normally discarded) and turn it into a per-phoneme timeline for the
        avatar's lip-sync. One pass — audio and timeline come from the same run."""
        self.load()
        pipe = self._handle["pipe"]
        voice = self._handle["voice"]
        sr = int(self.spec.get("sample_rate", 24000))

        audio_parts: list[np.ndarray] = []
        timeline: list[dict] = []
        cursor_s = 0.0
        for chunk in pipe(text, voice=voice):
            samples = np.asarray(chunk[2], dtype=np.float32)
            audio_parts.append(samples)
            chunk_dur = len(samples) / sr
            # Prefer Kokoro's model-native per-phoneme timing (the duration
            # predictor exposes start/end per token); fall back to spreading the
            # chunk's phoneme string when a build doesn't populate timestamps.
            tl = token_timeline(getattr(chunk, "tokens", None), cursor_s)
            if tl is None:
                tl = phoneme_timeline(chunk[1] or "", cursor_s, chunk_dur)
            timeline.extend(tl)
            cursor_s += chunk_dur

        audio = np.concatenate(audio_parts) if audio_parts else np.zeros(1, dtype=np.float32)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        self.sample_rate = sr
        duration_ms = int(len(pcm) / 2 / sr * 1000)
        a = Audio(data=self.pcm_to_wav(pcm, sr), sample_rate=sr,
                  duration_ms=duration_ms, lang=lang)
        return a, timeline


register_adapter(
    "kokoro",
    lambda logical_name, spec, env: KokoroTTSAdapter(logical_name, spec, env),
)
