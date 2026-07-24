"""TTS bench harness — compare voice engines on real intake questions.

Kiosk-perspective metrics per engine: model load time, per-utterance synthesis
time + RTF (synth / audio duration), output quality proxies (peak amplitude,
zero-crossing rate — ZCR ~0.05-0.15 = speech, ~0.5 = noise), and clip size.
Clips are saved under bench/results_tts/<engine>/ so a human can listen and score
naturalness (the axis a script can't measure).

Usage:  python -m bench.runner_tts                 # all wired engines
        python -m bench.runner_tts piper_hi mms    # a subset
"""

from __future__ import annotations

import sys
import time
import wave
from io import BytesIO
from pathlib import Path

import numpy as np

import models  # noqa: F401  (register adapters)
from core.env import AppConfig, EnvProfile

# Representative Hindi intake utterances: static (asked to everyone) + slotted
# (condition follow-ups with patient values — the live path that needs speed).
UTTERANCES = [
    ("static_meds", "क्या आप कोई दवा ले रहे हैं?"),
    ("static_allergy", "क्या आपको कोई एलर्जी है?"),
    ("slotted_glucose", "आपका Glucose Fasting 142 mg/dL है, जो अधिक है। क्या आपका मधुमेह का इलाज चल रहा है?"),
    ("slotted_creat", "आपका Creatinine 1.6 mg/dL है, जो अधिक है। क्या आपको गुर्दे की कोई समस्या है?"),
]


def _engines(env):
    # Shipped engines: Kokoro-82M for Hindi (Apache-2.0), Piper for English.
    # IndicF5 and MMS were benchmarked and removed (see record.md). Add a new
    # candidate here as a lambda building its adapter to benchmark it.
    from models.tts_kokoro import KokoroTTSAdapter
    from models.tts_piper import PiperTTSAdapter
    return {
        "kokoro_hi": lambda: KokoroTTSAdapter(
            "t", {"impl": "kokoro", "device": "cpu", "lang_code": "h",
                  "voice": "hf_alpha", "sample_rate": 24000}, env),
        # English reference (MIT engine + MIT lessac voice — commercial-clean).
        "piper_en": lambda: PiperTTSAdapter(
            "t", {"impl": "piper", "device": "cpu",
                  "voice": "models/weights/piper/en_US-lessac-medium.onnx"}, env),
        # NOTE: the "piper_hi" entry was REMOVED along with its weights. Every
        # off-the-shelf Piper Hindi voice is non-commercial (CC-BY-NC-SA / IIT-M),
        # so the .onnx must not ship — and a bench entry pointing at it would
        # silently re-download it. Historical numbers stay in record.md §9.
    }


def _wav_stats(data: bytes):
    with wave.open(BytesIO(data)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    dur = len(x) / sr
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    zcr = float(np.mean(np.abs(np.diff(np.sign(x)))) / 2) if x.size else 0.0
    return sr, dur, peak, zcr, len(data)


def run(engine_names: list[str]) -> None:
    env = EnvProfile.load("dev_4060")
    engines = _engines(env)
    out_root = Path("bench/results_tts")
    print(f"{'engine':10} {'load_s':>7} {'utt':16} {'audio_s':>7} {'synth_s':>8} {'RTF':>7} {'peak':>7} {'zcr':>6} {'kind':6}")
    print("-" * 92)
    summary = {}
    for name in engine_names:
        if name not in engines:
            print(f"  ! unknown engine {name}"); continue
        odir = out_root / name; odir.mkdir(parents=True, exist_ok=True)
        try:
            t0 = time.time(); adapter = engines[name](); adapter.load(); load_s = time.time() - t0
        except Exception as e:
            print(f"{name:10}  LOAD FAILED: {str(e)[:60]}"); continue
        rtfs = []; ok = True
        for uid, text in UTTERANCES:
            try:
                t0 = time.time(); audio = adapter.synthesize(text, "hi"); synth_s = time.time() - t0
                (odir / f"{uid}.wav").write_bytes(audio.data)
                sr, dur, peak, zcr, sz = _wav_stats(audio.data)
                rtf = synth_s / dur if dur else 0; rtfs.append(rtf)
                kind = "SPEECH" if (zcr < 0.2 and peak > 10000) else "BAD"
                print(f"{name:10} {load_s:7.1f} {uid:16} {dur:7.1f} {synth_s:8.2f} {rtf:7.2f} {peak:7.0f} {zcr:6.3f} {kind:6}")
            except Exception as e:
                print(f"{name:10} {'':7} {uid:16}  SYNTH FAILED: {str(e)[:50]}"); ok = False
        adapter.unload()
        if rtfs:
            summary[name] = {"load_s": round(load_s, 1), "mean_rtf": round(sum(rtfs) / len(rtfs), 2)}
    print("\n=== summary ===")
    for name, s in summary.items():
        realtime = "OK (faster than realtime)" if s["mean_rtf"] < 1 else "TOO SLOW for live"
        print(f"  {name:10} load {s['load_s']}s · mean RTF {s['mean_rtf']} -> {realtime}")
    print(f"\nClips saved under {out_root}/ — listen to score naturalness.")


if __name__ == "__main__":
    names = sys.argv[1:] or ["kokoro_hi"]
    run(names)
