// Live intake Q&A — speak each question aloud, record the spoken answer from
// the microphone, transcribe it through the pipeline STT. One question at a
// time (a patient cannot answer five at once). Mirrors the Streamlit panel:
// autoplay per question, re-record replaces, hashing/report gated until done.

import { useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, type Snapshot } from "./api";

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
  const audioEl = useRef<HTMLAudioElement>(null);

  // Question TTS clips: the voice stage names them "NN_question.wav"; lexical
  // order of those paths matches question order.
  const clips = useMemo(
    () =>
      c.audio_out
        .filter((a: any) => (a.path || "").replace(/\\/g, "/").match(/question\.wav$/i))
        .sort((a: any, b: any) => (a.path < b.path ? -1 : 1))
        .map((a: any) => a.path as string),
    [c.audio_out]
  );

  const answers: Record<string, any> = {};
  c.answers.forEach((a) => (answers[a.question_id] = a));
  const q = c.questions[idx];
  const answeredCount = c.answers.length;
  const total = c.questions.length;
  const last = idx >= total - 1;

  // Autoplay the question when it changes. Browsers may block autoplay if the
  // last user gesture was long ago — the visible controls are the fallback.
  useEffect(() => {
    audioEl.current?.play().catch(() => {});
  }, [idx]);

  async function startRec() {
    setMicError(null);
    try {
      // Clean the mic input — this is the real STT-accuracy lever (decode tuning
      // made Vaani WORSE; input quality is what fails ordinary words in a clinic):
      //  - echoCancellation: the kiosk speaks the question aloud; without this the
      //    speaker bleeds into the recording and corrupts the answer.
      //  - noiseSuppression: strips ambient clinic/kiosk noise.
      //  - autoGainControl: normalizes volume for soft/loud speakers at varying
      //    mic distance.
      //  - 16 kHz mono: Whisper's native rate, so no lossy resample.
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
    try {
      const s = await api.answer(snap.session_id, q.id, blob, "answer.webm");
      onSnap(s);
    } catch (e) {
      setMicError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!q) return null;
  const existing = answers[q.id];

  return (
    <div className="card" style={{ padding: 20, marginTop: 16 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>🎙 Live intake Q&amp;A</h3>
        <span className="muted" style={{ fontSize: 13 }}>{answeredCount} of {total} answered</span>
      </div>
      <div className="qa-progress"><div style={{ width: `${(answeredCount / total) * 100}%` }} /></div>

      <div style={{ marginTop: 14, fontWeight: 600, color: existing ? "var(--pass)" : "var(--ink-3)", fontSize: 13 }}>
        {existing ? "✓ " : ""}Question {idx + 1} of {total}
      </div>
      <div style={{ fontSize: 20, color: "var(--ink)", fontWeight: 700, margin: "4px 0 12px", lineHeight: 1.4 }}>
        {q.rendered_text}
      </div>

      {idx < clips.length ? (
        <audio ref={audioEl} key={`${snap.session_id}-${idx}`} src={fileUrl(clips[idx])}
          controls autoPlay controlsList="nodownload noplaybackrate" />
      ) : (
        <div className="cap">⚠ No audio clip for this question — text only.</div>
      )}

      <div className="row" style={{ marginTop: 14 }}>
        {!recording ? (
          <button className="btn-primary" onClick={startRec} disabled={busy}>
            {busy ? <><span className="spin">◍</span> Transcribing…</> : "● Record answer"}
          </button>
        ) : (
          <button className="btn-warn" onClick={stopRec}>■ Stop &amp; transcribe</button>
        )}
        {recording && <span className="rec-dot" />}
      </div>
      {micError && <div className="cap" style={{ color: "var(--crit)" }}>{micError}</div>}

      {existing && (
        <div className="banner ok" style={{ marginTop: 12 }}>
          <span><b>Answer recorded:</b> {existing.transcript || "— (empty)"}</span>
          <span className="cap" style={{ margin: 0 }}>Record again to replace this answer.</span>
        </div>
      )}

      <hr className="divider" style={{ margin: "18px 0" }} />
      <div className="row">
        <button className="btn-ghost" onClick={() => setIdx((i) => i - 1)} disabled={idx === 0}>← Back</button>
        {!last && <button className="btn-ghost" onClick={() => setIdx((i) => i + 1)}>Skip</button>}
        <div className="spacer" />
        {!last ? (
          <button className="btn-primary" onClick={() => setIdx((i) => i + 1)}>Next question →</button>
        ) : (
          <button className="btn-primary" onClick={onContinue} disabled={busy}>
            Continue → hashing &amp; report ▶
          </button>
        )}
      </div>
    </div>
  );
}
