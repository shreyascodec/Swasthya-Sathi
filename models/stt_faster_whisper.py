"""faster-whisper STT adapter (primary) for Stage [6] answer capture.

Transcribes recorded answer clips with CTranslate2-backed Whisper — small INT8
runs comfortably on CPU or the 4060. Multilingual, so it handles Hindi + English
answers. An Indic-conformer adapter can slot in later for stronger Indian-language
accuracy (config swap, no code change).

Setup: pip install faster-whisper
"""

from __future__ import annotations

from core.model_manager import register_adapter
from models.stt_base import STTAdapterBase, STTUnavailable, Transcript


class FasterWhisperAdapter(STTAdapterBase):
    default_vram_mb = 500

    def _build(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - env dependent
            raise STTUnavailable(
                "faster-whisper not installed. `pip install faster-whisper`, "
                "or swap stt to stub_stt."
            ) from exc
        # ``model_path`` points at a local CTranslate2 directory — that is how a
        # fine-tune is selected (IndicWhisper, Vaani-Hindi), and it keeps the
        # offline-first rule: a path never triggers a runtime download, whereas a
        # bare size name fetches from the Hub on first use. ``size`` remains the
        # fallback so existing configs keep working.
        model_ref = self.spec.get("model_path") or self.spec.get("size", "small")
        compute = self.spec.get("compute", "int8")
        device = "cuda" if self.is_gpu else "cpu"
        return {"model": WhisperModel(model_ref, device=device, compute_type=compute)}

    def _transcribe(self, audio_path: str, lang: str) -> Transcript:
        model = self._handle["model"]
        # lang=None lets Whisper auto-detect; pass the patient language as a hint.
        # NOTE: faster-whisper's DEFAULTS are already best for Vaani-Hindi here.
        # Measured on real kiosk clips, every "tuning" degraded it: vad_filter
        # clipped real speech into garble ("फ्रैक्चर"->"फ्लैक्चर", "दि दि दिखाया"),
        # and an initial_prompt sent the decoder into repetition loops
        # ("था था था"). So we deliberately do NOT pass decode overrides — the
        # accuracy lever is input AUDIO quality (mic noise-suppression), not
        # decode params.
        segments, info = model.transcribe(audio_path, language=lang or None)
        text = "".join(seg.text for seg in segments).strip()
        return Transcript(text=text, lang=getattr(info, "language", lang),
                          confidence=getattr(info, "language_probability", None))


register_adapter("faster-whisper",
                 lambda logical_name, spec, env: FasterWhisperAdapter(logical_name, spec, env))
