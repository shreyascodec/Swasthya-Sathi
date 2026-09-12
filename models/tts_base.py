"""Shared TTS adapter contract for Stage [7] Voice.

A TTS adapter turns text into speech audio in the patient language. It returns
WAV bytes plus timing (duration) — the STAGE writes the file, so adapters stay
filesystem-free (same split as the OCR adapters). Timing is the seam a later
Wav2Lip avatar attaches to (ARCHITECTURE: audio->video seam).

Same ModelManager lifecycle as every model (load/unload frees VRAM).
"""

from __future__ import annotations

import io
import logging
import wave
from dataclasses import dataclass

from core.env import EnvProfile

log = logging.getLogger("swasthya.tts")


class TTSUnavailable(ImportError):
    """Raised when a TTS runtime is missing."""


@dataclass
class Audio:
    data: bytes            # a complete WAV container
    sample_rate: int
    duration_ms: int
    lang: str


# --- Phoneme → viseme timeline (avatar lip-sync seam) --------------------------
# The 3D avatar wants a per-phoneme timeline (IPA symbol + start/end seconds) so
# it can drive mouth blendshapes. Engines that expose phonemes (Kokoro via misaki)
# build a real timeline; others return None and the avatar falls back to
# amplitude-driven jaw movement. Preferred timing is Kokoro's model-native
# per-token start/end (see ``token_timeline``); when a build doesn't expose it the
# durations are heuristic (vowels hold longer than consonants) then scaled to the
# chunk's real audio duration — the same approach the reference avatar server uses.
_VOWELS = set("æɑaəɛɪiɔoʊuʌɐeɜɒøyɘɵɪ̈")
_FRICATIVES = set("fsθðʃʒhvzɕʑxɣ")
_IPA_DIGRAPHS = ("dʒ", "tʃ", "aɪ", "aʊ", "ɔɪ", "eɪ", "oʊ", "d̪", "t̪")


def split_ipa(s: str) -> list[str]:
    """Split an IPA phoneme string into symbols, dropping stress/length marks."""
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == " ":
            out.append(" ")
            i += 1
        elif i + 1 < len(s) and s[i:i + 2] in _IPA_DIGRAPHS:
            out.append(s[i:i + 2])
            i += 2
        elif ch in ("ˈ", "ˌ", "ː", "ˑ"):   # stress / length markers — skip
            i += 1
        elif not ch.strip():
            i += 1
        else:
            out.append(ch)
            i += 1
    return out


def phoneme_timeline(ph_str: str, start_s: float, dur_s: float) -> list[dict]:
    """Distribute a chunk's phonemes across its audio duration (list of
    {phoneme, start, end}). Empty when there are no phonemes."""
    phs = split_ipa(ph_str or "")
    if not phs or dur_s <= 0:
        return []

    def weight(p: str) -> float:
        if p == " ":
            return 0.12
        if p in _VOWELS:
            return 0.10
        if p in _FRICATIVES:
            return 0.08
        return 0.06

    weights = [weight(p) for p in phs]
    total = sum(weights) or 1.0
    scale = dur_s / total
    out: list[dict] = []
    t = start_s
    for p, w in zip(phs, weights):
        d = w * scale
        out.append({"phoneme": p, "start": t, "end": t + d})
        t += d
    return out


def token_timeline(tokens, cursor_s: float = 0.0) -> list[dict] | None:
    """Per-phoneme timeline from misaki tokens carrying model-native start/end
    timestamps (Kokoro's duration predictor). Far tighter than
    :func:`phoneme_timeline`, which spreads a whole chunk's phonemes by a fixed
    heuristic — here each *word* token already has a measured ``[start, end]``
    window, so only the sub-word split is estimated, and real inter-word pauses
    become genuine gaps (the avatar's mouth closes between words).

    Returns ``None`` when the tokens carry no usable phonemes/timing, so the
    caller can fall back to the heuristic path. ``cursor_s`` offsets timestamps
    that are relative to the current chunk onto the absolute clip timeline.

    NOTE: Kokoro only assigns these timestamps on its English G2P path
    (``lang_code in 'ab'``). The Hindi/Indic EspeakG2P path yields tokens without
    ``start_ts``/``end_ts``, so this returns ``None`` for Hindi and the heuristic
    runs. The model's raw ``pred_dur`` is still exposed on the Result for every
    language — that is the seam for a real per-phoneme Hindi timeline.
    """
    if not tokens:
        return None
    out: list[dict] = []
    used = False
    for tok in tokens:
        ph = getattr(tok, "phonemes", None)
        if not ph:
            continue                                  # punctuation / whitespace token
        ts = getattr(tok, "start_ts", None)
        te = getattr(tok, "end_ts", None)
        if ts is None or te is None:
            return None                               # spoken token, no timing -> fall back
        ts, te = float(ts), float(te)
        if te <= ts:
            return None
        out.extend(phoneme_timeline(ph, cursor_s + ts, te - ts))
        used = True
    return out if used else None


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

    def synthesize_aligned(self, text: str, lang: str = "hi") -> tuple[Audio, list[dict] | None]:
        """Synthesise + return a phoneme timeline for avatar lip-sync.

        Default: no phoneme access → (audio, None); the avatar then drives the
        jaw from audio amplitude. Engines with a G2P front end (Kokoro) override
        this to return a real per-phoneme timeline.
        """
        return self.synthesize(text, lang), None

    #: Short utterance used by ``warm()``. Override per engine/language — the
    #: G2P front end is language-specific, so warming Hindi with English text
    #: would not touch the tables the first real question needs.
    warm_text: str = "ok"

    def warm(self) -> None:
        """One throwaway synthesis, called by the boot warmup.

        Loading the weights is not the whole cold start: the first synthesis also
        pays lazy CUDA kernel selection and G2P table init. Best-effort — the
        model is loaded and usable either way, so a failure here is logged, not
        raised, and must never mark a working engine unavailable.
        """
        try:
            self.synthesize(self.warm_text)
        except Exception as exc:  # noqa: BLE001 - warmup is best-effort by design
            log.warning("TTS warm() failed for %s: %s: %s",
                        self.logical_name, type(exc).__name__, exc)

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
