// Typed client for the Swasthya Sathi FastAPI backend.

export type StageStatus = "pending" | "running" | "done" | "flagged" | "error" | "skipped";

export interface StageMetric {
  label: string;
  value: string;
  kind?: "ok" | "flag" | null;
}

export interface StageInfo {
  name: string;
  order: number;
  description: string;
  status: StageStatus;
  elapsed: number | null;
  note: string;
  metrics: StageMetric[];
}

export interface Pause {
  kind: "flag" | "error" | "intake_qa";
  stage: string;
  detail: string;
}

export interface Faithfulness {
  score: number;
  ok: boolean;
  parse_error: string | null;
  issues: string[];
}

// The pipeline's SessionContext, serialized. Sub-shapes kept loose on purpose.
export interface Ctx {
  session_id: string;
  lang: string;
  uploads: any[];
  ocr: { raw_text: string; engine: string | null; fields: any[] } | null;
  image_tags: any[];
  summary: { version: number; content: any } | null;
  interpretations: any[];
  questions: any[];
  answers: any[];
  audio_out: any[];
  report: { version: number; sha256: string | null; content: any } | null;
  audit: { ts: string; actor: string; action: string; detail: string | null }[];
}

export interface Snapshot {
  session_id: string;
  lang: string;
  env: string;
  device: string;
  stages: StageInfo[];
  next_idx: number;
  total_stages: number;
  paused: Pause | null;
  done: boolean;
  ctx: Ctx;
  derived: {
    faithfulness: Faithfulness | null;
    recovered: string[];
    narrative_review: string[];
  };
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`${r.status}: ${body}`);
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
};

export const fileUrl = (path: string) => `/api/file?path=${encodeURIComponent(path)}`;
