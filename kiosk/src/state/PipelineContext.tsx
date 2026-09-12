import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type MaternalRisk, type Question, type Snapshot } from "../api/client";

// Outcome of driving the pipeline after an upload.
export type ProcessOutcome =
  | { kind: "questions"; questions: Question[] }
  | { kind: "no_questions" }
  | { kind: "error"; detail: string; reason: string };

interface PipelineValue {
  sessionId: string | null;
  snapshot: Snapshot | null;
  questions: Question[];
  summaryContent: any | null;
  maternalRisk: MaternalRisk | null;
  answerFor: (questionId: string) => string | null;
  /** Create a session (if needed) and upload the report file(s). */
  uploadReport: (files: File[], lang: string) => Promise<void>;
  /** Run stages until questions are ready, the run finishes, or it halts. */
  driveProcessing: () => Promise<ProcessOutcome>;
  /** Transcribe a recorded answer through pipeline STT; returns the transcript. */
  submitVoiceAnswer: (questionId: string, blob: Blob) => Promise<string>;
  /** Continue past the Q&A gate and seal the report (hashing + report stages). */
  finalize: () => Promise<void>;
  resetPipeline: () => void;
}

const PipelineContext = createContext<PipelineValue | null>(null);

const MAX_STEPS = 20; // hard stop; the pipeline is 9 stages

export function PipelineProvider({ children }: { children: ReactNode }) {
  const sessionIdRef = useRef<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);

  const uploadReport = useCallback(async (files: File[], lang: string) => {
    let sid = sessionIdRef.current;
    if (!sid) {
      const snap = await api.createSession(lang);
      sid = snap.session_id;
      sessionIdRef.current = sid;
      setSnapshot(snap);
    }
    const s = await api.upload(sid, files);
    setSnapshot(s);
  }, []);

  const driveProcessing = useCallback(async (): Promise<ProcessOutcome> => {
    const sid = sessionIdRef.current;
    if (!sid) return { kind: "error", detail: "No session.", reason: "no_session" };
    let s = snapshot;
    for (let i = 0; i < MAX_STEPS; i++) {
      s = await api.runStage(sid);
      setSnapshot(s);
      if (s.paused) {
        if (s.paused.kind === "intake_qa") {
          const qs = s.ctx.questions || [];
          return qs.length > 0 ? { kind: "questions", questions: qs } : { kind: "no_questions" };
        }
        // not_a_report | flag | error — halt and surface to the operator.
        return { kind: "error", detail: s.paused.detail, reason: s.paused.kind };
      }
      if (s.done) return { kind: "no_questions" };
    }
    return { kind: "error", detail: "The pipeline did not finish.", reason: "timeout" };
  }, [snapshot]);

  const submitVoiceAnswer = useCallback(async (questionId: string, blob: Blob): Promise<string> => {
    const sid = sessionIdRef.current;
    if (!sid) return "";
    const s = await api.answer(sid, questionId, blob, "answer.webm");
    setSnapshot(s);
    const a = (s.ctx.answers || []).find((x) => x.question_id === questionId);
    return a?.transcript ?? "";
  }, []);

  const finalize = useCallback(async () => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    let s = snapshot;
    if (s?.paused) {
      s = await api.resume(sid, "continue");
      setSnapshot(s);
    }
    for (let i = 0; i < MAX_STEPS && s && !s.done && !s.paused; i++) {
      s = await api.runStage(sid);
      setSnapshot(s);
    }
  }, [snapshot]);

  const resetPipeline = useCallback(() => {
    sessionIdRef.current = null;
    setSnapshot(null);
  }, []);

  const value = useMemo<PipelineValue>(() => {
    const answers: Record<string, string> = {};
    (snapshot?.ctx.answers || []).forEach((a) => (answers[a.question_id] = a.transcript));
    return {
      sessionId: sessionIdRef.current,
      snapshot,
      questions: snapshot?.ctx.questions || [],
      summaryContent: snapshot?.ctx.summary?.content ?? null,
      maternalRisk: snapshot?.derived?.maternal_risk ?? null,
      answerFor: (qid: string) => answers[qid] ?? null,
      uploadReport,
      driveProcessing,
      submitVoiceAnswer,
      finalize,
      resetPipeline,
    };
  }, [snapshot, uploadReport, driveProcessing, submitVoiceAnswer, finalize, resetPipeline]);

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>;
}

export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error("usePipeline must be used within PipelineProvider");
  return ctx;
}
