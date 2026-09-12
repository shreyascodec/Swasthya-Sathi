// Typed client for the Swasthya Sakhi FastAPI backend (the real pipeline).
// The kiosk SPA is served from the same origin as the API in production, so all
// paths are relative — no base URL, no CORS.

export interface Pause {
  kind: "flag" | "error" | "intake_qa" | "not_a_report";
  stage: string;
  detail: string;
}

export type RiskTier = "high" | "moderate" | "low" | "unknown";

export interface MaternalRisk {
  tier: RiskTier;
  tier_label: string;
  action: string;
  reasons: string[];
  red_flags: string[];
  parameters: { name: string; value: string; status: string }[];
  danger_signs: { question: string; answer: string; flag: boolean }[];
  gestational_age: string | null;
  reviewed: boolean;
  source: string;
}

export interface Question {
  id: string;
  pattern_id: string;
  rendered_text: string;
  lang: string;
}

// The serialized pipeline SessionContext. Sub-shapes kept loose on purpose —
// the kiosk only reads a few fields.
export interface Ctx {
  session_id: string;
  lang: string;
  ocr: { raw_text: string; engine: string | null; fields: any[] } | null;
  summary: { version: number; content: any } | null;
  interpretations: any[];
  questions: Question[];
  answers: { question_id: string; transcript: string; lang: string }[];
  report: { version: number; sha256: string | null; content: any } | null;
}

export interface Snapshot {
  session_id: string;
  lang: string;
  env: string;
  device: string;
  stages: { name: string; status: string; note: string }[];
  next_idx: number;
  total_stages: number;
  paused: Pause | null;
  done: boolean;
  ctx: Ctx;
  derived: {
    faithfulness: { score: number; ok: boolean; issues: string[] } | null;
    recovered: string[];
    narrative_review: string[];
    maternal_risk: MaternalRisk | null;
  };
}

export interface Readiness {
  ready: boolean;
  warming: boolean;
  loaded: string[];
  unavailable: string[];
  sessions: number;
}

export interface TtsClip {
  audio_base64: string;
  sample_rate: number;
  audio_duration: number;
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const body = await r.json();
      msg = body?.error?.message || body?.detail || JSON.stringify(body);
    } catch {
      try { msg = (await r.text()) || msg; } catch { /* keep default */ }
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  createSession: (lang: string) =>
    fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang }),
    }).then(j<Snapshot>),

  getSession: (sid: string) => fetch(`/api/session/${sid}`).then(j<Snapshot>),

  getReady: () => fetch("/api/ready").then(j<Readiness>),

  upload: (sid: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return fetch(`/api/session/${sid}/upload`, { method: "POST", body: fd }).then(j<Snapshot>);
  },

  runStage: (sid: string) =>
    fetch(`/api/session/${sid}/run-stage`, { method: "POST" }).then(j<Snapshot>),

  answer: (sid: string, questionId: string, blob: Blob, filename: string) => {
    const fd = new FormData();
    fd.append("question_id", questionId);
    fd.append("file", blob, filename);
    return fetch(`/api/session/${sid}/answer`, { method: "POST", body: fd }).then(j<Snapshot>);
  },

  resume: (sid: string, action: "continue" | "stop" | "retry") =>
    fetch(`/api/session/${sid}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }).then(j<Snapshot>),

  // Speak text with the pipeline's own Kokoro (Hindi) / Piper (English) voice.
  tts: (text: string, lang: string) =>
    fetch("/api/avatar/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang }),
    }).then(j<TtsClip>),
};
