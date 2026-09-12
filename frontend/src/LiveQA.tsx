// Live intake Q&A — a 3D avatar speaks each question aloud (with lip-sync driven
// by Stage [7] precomputed WAV + IPA alignment when available), then records the
// spoken answer from the microphone and transcribes it through pipeline STT.
// One question at a time. Hashing/report gated until done.

import { useEffect, useRef, useState } from "react";
import { api, type Snapshot } from "./api";
import { AvatarScene } from "./avatar/AvatarScene";
import { AvatarBoundary } from "./avatar/AvatarBoundary";
import { useAvatarTTS } from "./avatar/useAvatarTTS";

export function LiveQA({
  snap,
  onSnap,
  onContinue,
}: {
  snap: Snapshot;
  onSnap: (s: Snapshot) => void;
  onContinue: () => void;
}) {
  const c = snap.ctx;
  const [idx, setIdx] = useState(0);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  const { speak, speakClip, stop, speaking, amplitude, visemeRef, expressionRef, setExpression } = useAvatarTTS();

  const answers: Record<string, any> = {};
  c.answers.forEach((a) => (answers[a.question_id] = a));
  const q = c.questions[idx];
  const answeredCount = c.answers.length;
  const total = c.questions.length;
  const last = idx >= total - 1;

  function clipFor(questionId: string) {
    return c.audio_out.find((cl: any) => cl.question_id === questionId && cl.path);
  }

  function speakQuestion(question: any) {
    if (!question) return;
    const clip = clipFor(question.id);
    if (clip?.path) {
      speakClip({ path: clip.path, alignment: clip.alignment ?? null, text: question.rendered_text });
    } else if (question.rendered_text) {
      speak(question.rendered_text, c.lang);
    }
  }

  // Speak the current question when the index (or session) changes — NOT on
  // every snapshot. c.questions/c.audio_out get fresh identities on each answer
  // (server re-serializes ctx), which previously re-fired this effect and made
  // the avatar re-ask the just-answered question until the patient hit Next.
  // Q&A starts after Stage [7], so the precomputed clips are present on mount.
  useEffect(() => {
    speakQuestion(c.questions[idx]);
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, snap.session_id]);

  async function startRec() {
    setMicError(null);
    stop(); // don't record the avatar over the patient
    setExpression("neutral");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 16000,
          channelCount: 1,
        },
      });
      const mr = new MediaRecorder(stream, { audioBitsPerSecond: 128000 });
      chunks.current = [];
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
        await submit(blob);
      };
      mr.start();
      recorder.current = mr;
      setRecording(true);
    } catch (e) {
      setMicError("Microphone access was blocked. Allow it in the browser and try again.");
    }
  }

  function stopRec() {
    recorder.current?.stop();
    setRecording(false);
  }

  async function submit(blob: Blob) {
    if (!q) return;
    setBusy(true);
    setExpression("thinking");
    try {
      const s = await api.answer(snap.session_id, q.id, blob, "answer.webm");
      onSnap(s);
    } catch (e) {
      setMicError(String(e));
    } finally {
      setBusy(false);
      setExpression("neutral");
    }
  }

  if (!q) return null;
  const existing = answers[q.id];
  const hasClip = Boolean(clipFor(q.id)?.path);

  return (
    <div className="card qa-card">
      <div className="qa-topline">
        <h2>🎙 A few quick questions</h2>
        <span className="qa-count">{answeredCount} of {total} answered</span>
      </div>
      <div className="qa-progress"><div style={{ width: `${(answeredCount / total) * 100}%` }} /></div>

      <div className="qa-avatar" style={{ height: 300, borderRadius: 12, overflow: "hidden", margin: "12px 0" }}>
        <AvatarBoundary>
          <AvatarScene
            speaking={speaking}
            listening={recording}
            amplitude={amplitude}
            visemeRef={visemeRef}
            expressionRef={expressionRef}
          />
        </AvatarBoundary>
      </div>

      <div className={`qa-qmeta ${existing ? "answered" : ""}`}>
        {existing ? "✓ " : ""}Question {idx + 1} of {total}
        {hasClip ? " · precomputed voice" : " · live TTS"}
      </div>
      <div className="qa-question">{q.rendered_text}</div>

      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn-ghost" onClick={() => speakQuestion(q)} disabled={speaking}>
          {speaking ? "🔊 Speaking…" : "🔊 Repeat question"}
        </button>
      </div>

      <div style={{ marginTop: 18 }}>
        {!recording ? (
          <button className="btn-primary mic-btn" onClick={startRec} disabled={busy}>
            {busy ? <><span className="spin">◍</span> Transcribing…</> : "● Tap to record your answer"}
          </button>
        ) : (
          <button className="mic-btn rec" onClick={stopRec}>
            <span className="rec-dot" /> Recording — tap to stop
          </button>
        )}
      </div>
      {micError && <div className="cap" style={{ color: "var(--crit)" }}>{micError}</div>}

      {existing && (
        <div className="banner ok" style={{ marginTop: 14 }}>
          <span><b>Answer recorded:</b> {existing.transcript || "— (empty)"}</span>
          <span className="cap" style={{ margin: 0 }}>Record again to replace this answer.</span>
        </div>
      )}

      <hr className="divider" style={{ margin: "20px 0" }} />
      <div className="row">
        <button className="btn-ghost" onClick={() => setIdx((i) => i - 1)} disabled={idx === 0}>← Back</button>
        {!last && <button className="btn-ghost" onClick={() => setIdx((i) => i + 1)}>Skip</button>}
        <div className="spacer" />
        {!last ? (
          <button className="btn-primary" onClick={() => setIdx((i) => i + 1)}>Next question →</button>
        ) : (
          <button className="btn-primary" onClick={onContinue} disabled={busy}>
            Finish &amp; seal report ▶
          </button>
        )}
      </div>
    </div>
  );
}
