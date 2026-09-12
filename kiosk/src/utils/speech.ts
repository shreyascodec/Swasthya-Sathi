import type { Lang } from "../types";
import { api } from "../api/client";

// Avatar narration voice. PRIMARY path: the pipeline's OWN TTS (Kokoro Hindi /
// Piper English) via /api/avatar/tts — the same warm, commercial-clean Indic
// voice the kiosk ships, not the robotic browser voice. Falls back to the
// browser Web Speech API only if the backend call or playback fails (offline
// preview, TTS still warming, autoplay blocked), so narration never blocks the
// flow. speakText resolves when narration finishes, so callers can gate a screen
// transition on it (AvatarSpeechBubble.onNarrationEnd).

const langCode: Record<Lang, string> = { hi: "hi-IN", en: "en-IN" };

let currentAudio: HTMLAudioElement | null = null;
const clipCache = new Map<string, string>(); // `${lang}:${text}` -> object URL

// Tracks the most recent speakText call so a superseded call (a React effect
// that fired twice, rapid text changes) never plays after a newer one started.
let latestRequestId = 0;

function b64ToBlobUrl(b64: string): string {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
}

function browserSpeak(text: string, lang: Lang, requestId: number): Promise<void> {
  return new Promise((resolve) => {
    try {
      if (typeof window === "undefined" || !("speechSynthesis" in window)) return resolve();
      if (requestId !== latestRequestId) return resolve();
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = langCode[lang];
      u.rate = 0.98;
      u.pitch = 1.1;
      u.onend = () => resolve();
      u.onerror = () => resolve();
      window.speechSynthesis.speak(u);
    } catch {
      resolve();
    }
  });
}

export async function speakText(text: string, lang: Lang): Promise<void> {
  const requestId = ++latestRequestId;
  stopCurrentAudio();
  const clean = (text || "").trim();
  if (!clean) return;

  // Backend Kokoro/Piper first.
  const key = `${lang}:${clean}`;
  try {
    let url = clipCache.get(key);
    if (!url) {
      const clip = await api.tts(clean, lang);
      if (requestId !== latestRequestId) return; // superseded while fetching
      url = b64ToBlobUrl(clip.audio_base64);
      clipCache.set(key, url);
    }
    if (requestId !== latestRequestId) return;
    await new Promise<void>((resolve, reject) => {
      const audio = new Audio(url);
      currentAudio = audio;
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error("audio playback failed"));
      audio.play().catch(reject);
    });
  } catch {
    // Backend unavailable / autoplay blocked — degrade to the browser voice.
    await browserSpeak(clean, lang, requestId);
  }
}

function stopCurrentAudio() {
  if (currentAudio) {
    try { currentAudio.pause(); } catch { /* ignore */ }
    currentAudio = null;
  }
}

export function stopSpeech() {
  latestRequestId++; // invalidate any in-flight speakText call
  stopCurrentAudio();
  try {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  } catch { /* ignore */ }
}
