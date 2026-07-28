"""[7] Voice — speak the summary + intake questions in the patient language.

Voice ONLY (the avatar visual is deferred; ``avatar.enabled`` is respected). The
stage synthesizes the summary narrative and each intake question via the
configured TTS engine (Kokoro-82M for Hindi/Indic, Piper for English; stub_tts
for no-deps), writes
one WAV per utterance under the session's audio dir, and records an ``AudioClip``
— with ``duration_ms`` — into ``ctx.audio_out``. That clip + timing is the clean
audio->video seam a later Wav2Lip avatar attaches to (ARCHITECTURE §), so adding
the avatar needs no change here.

Tested/won/open: summary + question synthesis in the patient language, WAV
artifacts written, AudioClip timing seam emitted, avatar-disabled respected,
stub fallback + load/unload verified (tests/test_phase7.py). Open: real
Indic-TTS checkpoints on the 4060; streaming playback.
"""

from __future__ import annotations

from pathlib import Path

from core.context import AudioClip, SessionContext
from core.stage import Stage


class VoiceStage(Stage):
    name = "voice"
    order = 7
    description = "Speak questions + summary (TTS; avatar visual deferred)."

    def __init__(self, config, models) -> None:
        super().__init__(config, models)
        self._tts = None
        self._active_impl: str | None = None

    def _cfg(self) -> dict:
        return self.config.stage_cfg("voice")

    def _logical_for(self, lang: str) -> str:
        """Which TTS config drives this language. English routes to the English
        Piper voice (``tts_en``); every Indic language to the Hindi Kokoro engine
        (``tts``). A session is single-language, so one engine per run."""
        if lang == "en" and "tts_en" in self.config.models:
            return "tts_en"
        return "tts"

    def _configured_impl(self, logical: str = "tts") -> str:
        return self.config.models.get(logical, {}).get("primary", {}).get("impl", "stub_tts")

    def load(self, lang: str = "hi") -> None:
        """Load the language's Piper voice; on any failure (missing voice/deps)
        fall to the silent stub so the stage never crashes."""
        logical = self._logical_for(lang)
        self._logical = logical
        primary = self._configured_impl(logical)
        try:
            self._tts = self.models.get(logical)
            self._active_impl = primary
        except Exception:                      # missing voice/deps -> stub floor
            from models.tts_stub import StubTTSAdapter

            self.models.release(logical)
            self._tts = self.models.get(
                logical,
                factory=lambda logical_name, spec, env: StubTTSAdapter(
                    logical_name, {"impl": "stub_tts", "device": "cpu"}, env),
            )
            self._active_impl = f"{primary}->stub_tts(fallback)"

    def unload(self) -> None:
        # keep_warm (tts/tts_en primary in models.yaml) skips the release, same
        # knob as ocr.primary. Without it Stage.__call__'s guaranteed unload made
        # every session rebuild the engine — ~10 s of import + KPipeline build
        # per run — and, worse, evicted the very model server/warmup.py had kept
        # resident at boot, so the warmup only ever helped the first session.
        logical = getattr(self, "_logical", "tts")
        self._tts = None
        if self.config.models.get(logical, {}).get("primary", {}).get("keep_warm", False):
            return
        self.models.release(logical)

    def _avatar_enabled(self) -> bool:
        return bool(self.config.models.get("avatar", {}).get("primary", {}).get("enabled", False))

    def _audio_dir(self, ctx: SessionContext) -> Path:
        subdir = self._cfg().get("output_subdir", "audio")
        path = Path(self.env_data_dir()) / subdir / ctx.session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def env_data_dir(self) -> str:
        return self.config.env.data_dir

    _LANG_NAMES = {"hi": "Hindi (Devanagari script)", "mr": "Marathi (Devanagari script)",
                   "bn": "Bengali", "ta": "Tamil", "te": "Telugu"}

    def _translate_for_patient(self, text: str, lang: str) -> str:
        """Translate the English narrative into the patient language, right at
        the voice boundary (the stored summary stays English-only). Loads the
        LLM, translates, releases it before TTS loads (one heavy model at a
        time). Returns "" on any failure — the summary is then not spoken."""
        lang_name = self._LANG_NAMES.get(lang)
        if lang_name is None:
            return ""
        try:
            llm = self.models.get("llm")
            out = llm.generate(
                "You translate short medical summaries for patients.",
                f"Translate the following into {lang_name} ONLY. Keep all "
                "numbers, units and abbreviations exactly as they are. Return "
                "ONLY the translation, no prose:\n\n" + text,
                max_tokens=512,
            ).strip()
        except Exception:
            return ""
        finally:
            self.models.release("llm")
        if lang == "hi":
            from stages.summary_build import wrong_script_for_hindi

            if wrong_script_for_hindi(out):
                return ""
        return out

    def _utterances(self, ctx: SessionContext) -> list[tuple[str, str]]:
        """(kind, text) to speak, in play order: summary narrative, then questions."""
        items: list[tuple[str, str]] = []
        if self._cfg().get("speak_summary", True) and ctx.summary:
            narr = ctx.summary.content.get("narrative_en", "").strip()
            if narr and ctx.lang != "en" and self._cfg().get("translate_summary", True):
                # Fall back to the English narrative if translation fails —
                # an accented English readout beats silence.
                narr = self._translate_for_patient(narr, ctx.lang) or narr
            if narr:
                items.append(("summary", narr))
        if self._cfg().get("speak_questions", True):
            for q in ctx.questions:
                if q.rendered_text.strip():
                    items.append(("question", q.rendered_text.strip()))
        max_clips = int(self._cfg().get("max_clips", 12))
        return items[:max_clips]

    def run(self, ctx: SessionContext) -> SessionContext:
        # Piper is fast (RTF ~0.03), so every utterance is synthesized live — no
        # caching/pre-rendering needed (that scaffolding was for IndicF5's ~90s
        # synthesis and was removed once Piper became the engine; see record.md).
        if self._tts is None:
            self.load(ctx.lang)
        out_dir = self._audio_dir(ctx)
        clips: list[AudioClip] = []
        for i, (kind, text) in enumerate(self._utterances(ctx)):
            audio = self._tts.synthesize(text, lang=ctx.lang)
            path = out_dir / f"{i:02d}_{kind}.wav"
            path.write_bytes(audio.data)
            clips.append(AudioClip(
                id=f"{ctx.session_id}:tts:{i:02d}", path=str(path),
                lang=ctx.lang, kind="tts", duration_ms=audio.duration_ms))
        ctx.audio_out = clips
        total_ms = sum(c.duration_ms or 0 for c in clips)
        ctx.log(
            "stage.voice.done",
            detail=(f"impl={self._active_impl} avatar_enabled={self._avatar_enabled()} "
                    f"clips={len(clips)} total_ms={total_ms}"),
        )
        return ctx
