// Drives the 3D avatar from pipeline TTS.
// Prefer Stage [7] precomputed clips (WAV path + IPA alignment on AudioClip) so
// LiveQA does not re-synthesize. Fall back to POST /api/avatar/tts for
// ad-hoc / missing clips. When alignment is empty (e.g. Piper), visemes stay
// 'sil' and jaw follows audio amplitude.

import { useCallback, useRef, useState } from "react";
import { fileUrl } from "../api";
import { CLINIC_QUESTION_EXPR, detectExpression } from "./expressions";

const AVATAR_TTS_API = "/api/avatar/tts";

const PHONEME_TO_VISEME: Record<string, string> = {
  " ": "sil", "": "sil",
  p: "PP", b: "PP", m: "PP",
  f: "FF", v: "FF",
  "θ": "TH", "ð": "TH",
  t: "DD", d: "DD", n: "nn", l: "DD",
  "ɾ": "DD", "ɹ": "RR", "ɽ": "RR",
  "ʈ": "DD", "ɖ": "DD", "ɳ": "nn",
  "ʃ": "CH", "ʒ": "CH", "tʃ": "CH", "dʒ": "CH", c: "CH", "ɟ": "DD",
  k: "kk", g: "kk", "ŋ": "nn", x: "kk", "ɣ": "kk",
  s: "SS", z: "SS", "ɕ": "SS", "ʑ": "SS",
  h: "sil", "ʔ": "sil", "ʰ": "aa",
  w: "U", j: "I",
  r: "RR",
  "æ": "aa", a: "aa", "ɑ": "aa", "ä": "aa", "ʌ": "aa", "ɐ": "aa",
  e: "E", "ɛ": "E", "ə": "E", "ɜ": "E",
  "ɪ": "I", i: "I",
  "ɔ": "O", o: "O", "ɒ": "O",
  "ʊ": "U", u: "U",
  "aɪ": "aa", "aʊ": "aa", "ɔɪ": "O", "eɪ": "E", "oʊ": "O",
};

function phonemeToViseme(ph: string): string {
  return PHONEME_TO_VISEME[ph] ?? PHONEME_TO_VISEME[ph?.toLowerCase?.()] ?? "sil";
}

interface TLEntry { time: number; viseme: string; phoneme: string; duration: number }

export interface PhonemeSpan {
  phoneme: string;
  start: number;
  end: number;
}

export interface PrecomputedClip {
  path: string;
  alignment?: PhonemeSpan[] | null;
  /** Optional spoken text — drives expression + head gesture. */
  text?: string | null;
}

function consolidate(raw: TLEntry[]): TLEntry[] {
  const MIN_HOLD = 0.05;
  const held: TLEntry[] = [];
  for (const entry of raw) {
    const prev = held[held.length - 1];
    if (prev && entry.duration < MIN_HOLD && entry.viseme !== "sil") {
      prev.duration += entry.duration;
    } else {
      held.push({ ...entry });
    }
  }
  const merged: TLEntry[] = [];
  for (const entry of held) {
    const prev = merged[merged.length - 1];
    if (prev && prev.viseme === entry.viseme) {
      prev.duration += entry.duration;
    } else {
      merged.push({ ...entry });
    }
  }
  return merged;
}

function buildTimeline(characters: string[], starts: number[], ends: number[]): TLEntry[] {
  const raw: TLEntry[] = [];
  for (let i = 0; i < characters.length; i++) {
    const dur = ends[i] - starts[i];
    if (dur <= 0) continue;
    raw.push({ time: starts[i], viseme: phonemeToViseme(characters[i]), phoneme: characters[i], duration: dur });
  }
  return consolidate(raw);
}

function timelineFromSpans(spans: PhonemeSpan[] | null | undefined): TLEntry[] {
  if (!spans?.length) return [];
  const raw: TLEntry[] = [];
  for (const e of spans) {
    const dur = e.end - e.start;
    if (dur <= 0) continue;
    raw.push({ time: e.start, viseme: phonemeToViseme(e.phoneme), phoneme: e.phoneme, duration: dur });
  }
  return consolidate(raw);
}

export function useAvatarTTS() {
  const [speaking, setSpeaking] = useState(false);
  const [amplitude, setAmplitude] = useState(0);

  const visemeRef = useRef<string>("sil");
  const expressionRef = useRef<string>("neutral");
  const audioCtxRef = useRef<AudioContext | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const startTimeRef = useRef(0);
  const timelineRef = useRef<TLEntry[]>([]);

  const applyTextCues = useCallback((text: string | null | undefined, asQuestion: boolean) => {
    const fallback = asQuestion ? CLINIC_QUESTION_EXPR : "neutral";
    expressionRef.current = detectExpression(text || "", fallback);
    if (text) {
      try { (expressionRef as any)._triggerGesture?.(text); } catch { /* canvas may not be mounted */ }
    }
  }, []);

  const stop = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
    setSpeaking(false);
    setAmplitude(0);
    visemeRef.current = "sil";
    expressionRef.current = "neutral";
    timelineRef.current = [];
  }, []);

  const playBytes = useCallback(async (bytes: ArrayBuffer, timeline: TLEntry[], signal: AbortSignal) => {
    if (signal.aborted) return;
    const audioCtx = new AudioContext();
    audioCtxRef.current = audioCtx;
    if (audioCtx.state === "suspended") { try { await audioCtx.resume(); } catch { /* ignore */ } }
    const decoded = await audioCtx.decodeAudioData(bytes.slice(0));
    if (signal.aborted) { audioCtx.close().catch(() => {}); return; }

    const source = audioCtx.createBufferSource();
    source.buffer = decoded;
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(audioCtx.destination);
    const freqData = new Uint8Array(analyser.frequencyBinCount);

    timelineRef.current = timeline;
    setSpeaking(true);
    startTimeRef.current = audioCtx.currentTime;

    const tick = () => {
      const elapsed = audioCtx.currentTime - startTimeRef.current;
      analyser.getByteFrequencyData(freqData);
      const slice = freqData.slice(2, 20);
      setAmplitude(slice.reduce((a, b) => a + b, 0) / slice.length / 255);

      const tl = timelineRef.current;
      let v = "sil";
      for (let i = 0; i < tl.length; i++) {
        if (elapsed >= tl[i].time - 0.03 && elapsed < tl[i].time + tl[i].duration) {
          v = tl[i].viseme;
          break;
        }
      }
      visemeRef.current = v;
      animFrameRef.current = requestAnimationFrame(tick);
    };
    tick();

    source.onended = () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      setSpeaking(false);
      setAmplitude(0);
      visemeRef.current = "sil";
      expressionRef.current = "neutral";
      timelineRef.current = [];
      audioCtx.close().catch(() => {});
      audioCtxRef.current = null;
    };

    source.start();
  }, []);

  /** Speak via live TTS (ad-hoc / missing Stage-7 clip). */
  const speak = useCallback(async (text: string, lang = "hi") => {
    stop();
    const controller = new AbortController();
    abortRef.current = controller;
    applyTextCues(text, true);

    try {
      const res = await fetch(AVATAR_TTS_API, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, lang }),
      });
      if (!res.ok) throw new Error(`avatar tts ${res.status}`);
      const json = await res.json();

      const binaryStr = atob(json.audio_base64);
      const bytes = new Uint8Array(binaryStr.length);
      for (let i = 0; i < binaryStr.length; i++) bytes[i] = binaryStr.charCodeAt(i);

      const aln = json.normalized_alignment ?? json.alignment ?? { characters: [] };
      const timeline = (aln.characters?.length)
        ? buildTimeline(aln.characters, aln.character_start_times_seconds, aln.character_end_times_seconds)
        : [];

      await playBytes(bytes.buffer, timeline, controller.signal);
    } catch (err: any) {
      if (err?.name !== "AbortError") console.error("[avatar tts]", err);
      setSpeaking(false);
      setAmplitude(0);
      visemeRef.current = "sil";
      expressionRef.current = "neutral";
    }
  }, [stop, playBytes, applyTextCues]);

  /** Replay a Stage [7] WAV + alignment (no re-synthesis). */
  const speakClip = useCallback(async (clip: PrecomputedClip) => {
    stop();
    const controller = new AbortController();
    abortRef.current = controller;
    applyTextCues(clip.text, true);

    try {
      const res = await fetch(fileUrl(clip.path), { signal: controller.signal });
      if (!res.ok) throw new Error(`avatar clip ${res.status}`);
      const bytes = await res.arrayBuffer();
      await playBytes(bytes, timelineFromSpans(clip.alignment), controller.signal);
    } catch (err: any) {
      if (err?.name !== "AbortError") console.error("[avatar clip]", err);
      setSpeaking(false);
      setAmplitude(0);
      visemeRef.current = "sil";
      expressionRef.current = "neutral";
    }
  }, [stop, playBytes, applyTextCues]);

  const setExpression = useCallback((expr: string) => {
    expressionRef.current = expr;
  }, []);

  return { speak, speakClip, stop, speaking, amplitude, visemeRef, expressionRef, setExpression };
}
