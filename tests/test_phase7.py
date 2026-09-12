"""Phase 7 acceptance tests (PLAN.md Phase 7 — Voice/TTS).

VARIANT (poc testing2): the summary is never spoken and never translated —
voice covers the intake questions only, in the patient language. Covers valid
WAV artifacts written, the AudioClip timing seam (duration_ms) for the future
avatar, avatar-disabled being respected, the stub fallback when Indic-TTS isn't
provisioned, and load/unload.
"""

from __future__ import annotations

import wave
from pathlib import Path

from core.context import IntakeQuestion, SessionContext, SummaryDoc
from core.pipeline import Pipeline
from models.tts_stub import StubTTSAdapter


def _ctx() -> SessionContext:
    ctx = SessionContext(session_id="p7test", lang="hi")
    ctx.summary = SummaryDoc(version=1, content={
        "narrative_en": "Your hemoglobin is 9.5, which is low.",
    })
    ctx.questions = [
        IntakeQuestion(id="p7test:q1", pattern_id="cond_anemia",
                       rendered_text="क्या आप अक्सर थकान महसूस करते हैं?", lang="hi"),
        IntakeQuestion(id="p7test:q2", pattern_id="std_current_meds",
                       rendered_text="क्या आप कोई दवा ले रहे हैं?", lang="hi"),
    ]
    return ctx


def _pipeline(tmp_path) -> Pipeline:
    p = Pipeline(env_name="dev_4060")
    p.config.env.data_dir = str(tmp_path)     # keep artifacts out of the repo
    # Force the stub voice so stage tests stay fast/deterministic (no model
    # download). The real Kokoro/Piper primaries are exercised separately.
    p.config.models["tts"]["primary"] = {"impl": "stub_tts", "device": "cpu",
                                         "sample_rate": 22050}
    # Skip the voice-boundary LLM translation (would load the real LLM);
    # the English narrative is spoken as-is.
    p.config.stages["voice"]["translate_summary"] = False
    return p


# --- stub adapter directly ---------------------------------------------------
def test_stub_tts_makes_valid_wav_with_scaled_duration(tmp_path) -> None:
    from core.env import AppConfig
    env = AppConfig.load("dev_4060").env
    tts = StubTTSAdapter("tts", {"device": "cpu", "sample_rate": 22050}, env)

    short = tts.synthesize("नमस्ते", "hi")
    long = tts.synthesize("यह एक बहुत लंबा वाक्य है जिसे बोलने में अधिक समय लगेगा।", "hi")
    assert long.duration_ms > short.duration_ms          # longer text -> longer clip

    out = tmp_path / "clip.wav"
    out.write_bytes(short.data)
    with wave.open(str(out)) as wf:
        assert wf.getframerate() == 22050
        assert wf.getnframes() > 0


# --- stage end-to-end --------------------------------------------------------
def test_voice_speaks_questions_only(tmp_path) -> None:
    p = _pipeline(tmp_path)
    ctx = p.run_stage("voice", _ctx())

    assert len(ctx.audio_out) == 2               # 2 questions, summary NOT spoken
    assert [c.question_id for c in ctx.audio_out] == ["p7test:q1", "p7test:q2"]
    for clip in ctx.audio_out:
        assert clip.kind == "tts" and clip.lang == "hi"
        assert clip.utterance == "question"
        assert clip.duration_ms and clip.duration_ms > 0   # timing seam present
        assert Path(clip.path).exists()
        assert "summary" not in Path(clip.path).name       # variant invariant

    with wave.open(ctx.audio_out[0].path) as wf:
        assert wf.getnframes() > 0               # first clip is a real WAV

    assert p.models.loaded == []                 # TTS unloaded after the stage
    assert any(e.action == "stage.voice.done" for e in ctx.audit)


def test_questions_in_play_order(tmp_path) -> None:
    p = _pipeline(tmp_path)
    ctx = p.run_stage("voice", _ctx())
    assert ctx.audio_out[0].path.endswith("00_question.wav")
    assert ctx.audio_out[1].path.endswith("01_question.wav")


def test_speak_flags_respected(tmp_path) -> None:
    p = _pipeline(tmp_path)
    p.config.stages["voice"]["speak_questions"] = False
    ctx = p.run_stage("voice", _ctx())
    assert len(ctx.audio_out) == 0               # nothing left to speak

    # Opting the summary back in via config still works (seam kept).
    p2 = _pipeline(tmp_path)
    p2.config.stages["voice"]["speak_summary"] = True
    ctx2 = p2.run_stage("voice", _ctx())
    assert len(ctx2.audio_out) == 3              # summary + 2 questions
    assert ctx2.audio_out[0].path.endswith("00_summary.wav")


def test_avatar_disabled_respected(tmp_path) -> None:
    p = _pipeline(tmp_path)
    assert p.config.models["avatar"]["primary"]["enabled"] is False
    ctx = p.run_stage("voice", _ctx())
    detail = next(e.detail for e in ctx.audit if e.action == "stage.voice.done")
    assert "avatar_enabled=False" in detail
    # Voice-only: every artifact is audio, nothing else emitted.
    assert all(c.kind == "tts" for c in ctx.audio_out)


def test_unavailable_primary_falls_back_and_still_speaks(tmp_path) -> None:
    # An unavailable primary (bad impl / missing voice) must never silence the
    # kiosk: the stage falls back to the silent stub and still produces clips.
    p = _pipeline(tmp_path)
    p.config.models["tts"]["primary"] = {"impl": "piper", "device": "cpu",
                                         "voice": "does-not-exist.onnx"}
    ctx = p.run_stage("voice", _ctx())
    assert len(ctx.audio_out) == 2               # audio produced anyway
    detail = next(e.detail for e in ctx.audit if e.action == "stage.voice.done")
    assert "fallback" in detail


def test_commercial_clean_tts_defaults() -> None:
    # Final voice split, both commercial-clean:
    #   HINDI/Indic -> Kokoro-82M (Apache-2.0, incl. voices)
    #   ENGLISH     -> Piper (MIT engine + MIT lessac voice)
    # Kokoro replaced Piper on Hindi because every off-the-shelf Piper Hindi voice
    # is non-commercial (CC-BY-NC-SA / IIT-M). IndicF5 / MMS were removed earlier.
    # See commercial.md §0 / record.md §9.
    from core.env import AppConfig
    cfg = AppConfig.load("dev_4060")
    assert cfg.models["tts"]["primary"]["impl"] == "kokoro"
    assert cfg.models["tts_en"]["primary"]["impl"] == "piper"


def test_wav_gets_a_silence_tail() -> None:
    """A long utterance must not end on its final sample.

    VITS ends long questions abruptly (measured: 0.03s trailing silence on the
    longest intake question vs 0.2-0.4s on shorter ones), which plays back as
    the question being cut off mid-word.
    """
    import wave, io, array
    from models.tts_base import TTSAdapterBase

    sr = 16000
    pcm = (b"\x40\x00" * sr)                       # 1s of non-silent tone
    wav = TTSAdapterBase.pcm_to_wav(pcm, sr, tail_ms=300)

    with wave.open(io.BytesIO(wav)) as w:
        frames = w.getnframes()
        samples = array.array("h")
        samples.frombytes(w.readframes(frames))

    assert frames == sr + int(sr * 0.3), f"expected 1.3s of frames, got {frames/sr:.2f}s"
    trailing = 0
    for s in reversed(samples):
        if s != 0:
            break
        trailing += 1
    assert trailing >= int(sr * 0.25), "silence tail missing — playback will clip the last syllable"


def test_wav_tail_can_be_disabled() -> None:
    from models.tts_base import TTSAdapterBase
    import wave, io

    sr = 16000
    wav = TTSAdapterBase.pcm_to_wav(b"\x40\x00" * sr, sr, tail_ms=0)
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getnframes() == sr


# --- avatar lip-sync timeline (model-native phoneme timing) ------------------
class _FakeToken:
    """Stand-in for a misaki token carrying the duration predictor's timing."""

    def __init__(self, phonemes, start_ts, end_ts):
        self.phonemes = phonemes
        self.start_ts = start_ts
        self.end_ts = end_ts


def test_token_timeline_uses_native_timestamps() -> None:
    # Two words with measured windows [0.00,0.30] and [0.40,0.90]; the [0.30,0.40]
    # inter-word pause must become a genuine gap (mouth closes between words).
    from models.tts_base import token_timeline

    tl = token_timeline([_FakeToken("hə", 0.0, 0.30), _FakeToken("loʊ", 0.40, 0.90)], cursor_s=1.0)
    assert tl, "expected a timeline built from native timestamps"
    assert abs(tl[0]["start"] - 1.0) < 1e-6            # onset = cursor + first token start
    assert all(e["end"] > e["start"] for e in tl)
    first = [e for e in tl if e["start"] < 1.35]       # first word stays inside its window
    assert max(e["end"] for e in first) <= 1.30 + 1e-6
    assert any(e["start"] >= 1.40 - 1e-6 for e in tl)  # second word begins after the pause
    assert max(e["end"] for e in tl) <= 1.90 + 1e-6


def test_token_timeline_skips_punctuation_tokens() -> None:
    from models.tts_base import token_timeline

    tl = token_timeline([_FakeToken("haɪ", 0.0, 0.3), _FakeToken("", None, None)])
    assert tl and all(e["phoneme"] for e in tl)


def test_token_timeline_falls_back_when_timing_missing() -> None:
    # A spoken token without usable timing -> None so the caller uses the heuristic.
    from models.tts_base import token_timeline

    assert token_timeline([_FakeToken("haɪ", None, None)]) is None
    assert token_timeline([_FakeToken("haɪ", 0.3, 0.3)]) is None   # zero-width window
    assert token_timeline([]) is None
    assert token_timeline(None) is None


def test_piper_english_produces_real_audio(tmp_path) -> None:
    """English routes to Piper and produces real (non-silent) audio.

    Skips cleanly if piper or its voice model isn't provisioned in this env.
    """
    import wave, array
    import pytest
    from core.env import AppConfig, EnvProfile
    from models.tts_piper import PiperTTSAdapter

    env = EnvProfile.load("dev_4060")
    spec = AppConfig.load("dev_4060").models["tts_en"]["primary"]
    adapter = PiperTTSAdapter("tts_en", spec, env)
    try:
        audio = adapter.synthesize("Are you taking any medication?", lang="en")
    except Exception as e:  # not provisioned here
        pytest.skip(f"Piper not provisioned: {e}")

    import io
    with wave.open(io.BytesIO(audio.data)) as w:
        a = array.array("h"); a.frombytes(w.readframes(w.getnframes()))
    rms = (sum(x * x for x in a) / len(a)) ** 0.5
    assert rms > 500, "Piper output is silent"
    assert audio.duration_ms > 0
