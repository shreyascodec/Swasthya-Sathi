import { useEffect, useRef, useState } from "react";
import { api, type Snapshot, type StageInfo } from "./api";
import { StageBody } from "./StageBody";
import { LiveQA } from "./LiveQA";

// code -> display name. Values stay ISO codes (the backend expects "hi" etc.).
const LANGS: [string, string][] = [
  ["hi", "Hindi"],
  ["en", "English"],
  ["mr", "Marathi"],
  ["bn", "Bengali"],
  ["ta", "Tamil"],
  ["te", "Telugu"],
];
const DOT: Record<string, string> = { done: "✓", flagged: "!", error: "✕", running: "", pending: "" };

function fmtBytes(n: number) {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

export default function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [lang, setLang] = useState("hi");
  const [staged, setStaged] = useState<File[]>([]);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [over, setOver] = useState(false);
  // Transport-level failure (backend down, session lost after a restart). Shown
  // as an inline banner, never alert(): a modal dialog on a kiosk blocks the
  // whole screen until someone finds a keyboard to dismiss it.
  const [err, setErr] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Create a session on first load.
  useEffect(() => {
    api.createSession(lang).then(setSnap).catch((e) => setErr(`Backend not reachable. ${e}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function newSession(l = lang) {
    setStaged([]); setOpen({}); setRunning(false);
    setSnap(await api.createSession(l));
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    setStaged((prev) => [...prev, ...Array.from(list)]);
  }

  // Drive the stage loop one call at a time — mirrors the Streamlit stepper.
  async function process() {
    if (!snap) return;
    setRunning(true);
    setErr(null);
    try {
      let s = staged.length ? await api.upload(snap.session_id, staged) : snap;
      setSnap(s); setStaged([]);
      while (!s.done && !s.paused) {
        // optimistic: show the next stage as running while its call is in flight
        const nextName = s.stages[s.next_idx]?.name;
        if (nextName) {
          setSnap({ ...s, stages: s.stages.map((st) => st.name === nextName ? { ...st, status: "running" } : st) });
        }
        s = await api.runStage(s.session_id);
        setSnap(s);
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setRunning(false);
    }
  }

  async function resume(action: "continue" | "stop" | "retry") {
    if (!snap) return;
    setRunning(true);
    setErr(null);
    // The resume call itself is inside the try: if the session is gone (backend
    // restarted), it 404s, and without a catch the rejection was unhandled and
    // the run just stopped with no explanation on screen.
    try {
      let s = await api.resume(snap.session_id, action);
      setSnap(s);
      if (action === "stop") return;
      while (!s.done && !s.paused) {
        const nextName = s.stages[s.next_idx]?.name;
        if (nextName) setSnap({ ...s, stages: s.stages.map((st) => st.name === nextName ? { ...st, status: "running" } : st) });
        s = await api.runStage(s.session_id);
        setSnap(s);
      }
    } catch (e) {
      setErr(String(e));
    } finally { setRunning(false); }
  }

  if (!snap) return <div style={{ padding: 40 }} className="muted">Connecting to pipeline…</div>;

  const answered = snap.ctx.answers.length;
  const totalDone = snap.stages.filter((s) => s.status === "done" || s.status === "flagged").length;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="hi"><span className="brand-mark">📋</span> स्वास्थ्य साथी</div>
          <div className="en">Swasthya Sathi</div>
        </div>

        <div className="side-block">
          <span className="side-label">Environment</span>
          <span className="side-val">{snap.env} · {snap.device}</span>
        </div>

        <div className="side-block">
          <span className="side-label">Session</span>
          <span className="side-val">{snap.session_id}</span>
        </div>

        <div className="side-block">
          <span className="side-label">Patient language</span>
          <select className="lang" value={lang} disabled={running}
            onChange={(e) => { setLang(e.target.value); newSession(e.target.value); }}>
            {LANGS.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        </div>

        <button className="btn-ghost" onClick={() => newSession()} disabled={running}>New session</button>
      </aside>

      <main className="main">
        <div className="hero">
          <h1>Upload → process → report</h1>
          <p>Upload report images or PDFs, then run the pipeline. Each of the nine stages runs in order with live status; open any completed stage to inspect its output.</p>
        </div>

        <div
          className={`drop ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files); }}
        >
          <h3>Drag &amp; drop report files here</h3>
          <p>JPG · PNG · BMP · TIFF · WEBP · PDF</p>
          <button className="btn-ghost" onClick={() => fileInput.current?.click()} disabled={running}>Browse files</button>
          <input ref={fileInput} type="file" hidden multiple
            accept=".jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp,.pdf"
            onChange={(e) => addFiles(e.target.files)} />
        </div>

        {staged.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
            {staged.map((f, i) => (
              <div className="file-row" key={i}>
                <span className="name">{f.name}</span>
                <span className="size">{fmtBytes(f.size)}</span>
                <button className="x" onClick={() => setStaged((p) => p.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
          </div>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn-primary" onClick={process}
            disabled={running || (!staged.length && !snap.ctx.uploads.length)}>
            {running ? <><span className="spin">◍</span> Processing…</> : `▶ Process${staged.length ? ` ${staged.length} file(s)` : ""}`}
          </button>
          {snap.ctx.uploads.length > 0 && (
            <span className="muted" style={{ fontSize: 12.5 }}>Session has {snap.ctx.uploads.length} file(s)</span>
          )}
        </div>

        {/* Transport failure — distinct from a pipeline pause, which is a normal gate. */}
        {err && (
          <div className="banner crit">
            <b>✕ Could not reach the pipeline</b>
            <span>{err}</span>
            <div className="actions">
              <button className="btn-ghost" onClick={() => { setErr(null); newSession(); }}>
                Start a new session
              </button>
              <button className="btn-ghost" onClick={() => setErr(null)}>Dismiss</button>
            </div>
          </div>
        )}

        {/* Live intake Q&A gate — the patient interaction, before the report is sealed. */}
        {snap.paused?.kind === "intake_qa" && (
          <LiveQA snap={snap} onSnap={setSnap} onContinue={() => resume("continue")} />
        )}

        {/* Quality / error / parse gates. */}
        {snap.paused && snap.paused.kind !== "intake_qa" && (
          <div className={`banner ${snap.paused.kind === "error" ? "crit" : "warn"}`}>
            <b>{snap.paused.kind === "error" ? "✕" : "⚠"} Paused after “{snap.paused.stage}”</b>
            <span>{snap.paused.detail}</span>
            <div className="actions">
              {snap.paused.kind === "error"
                ? <button className="btn-ghost" onClick={() => resume("retry")}>Retry stage</button>
                : <button className="btn-primary" onClick={() => resume("continue")}>Continue ▶</button>}
              <button className="btn-ghost" onClick={() => resume("stop")}>Stop run</button>
            </div>
          </div>
        )}

        <div className="steps">
          {snap.stages.map((s: StageInfo) => {
            const expandable = s.status === "done" || s.status === "flagged";
            const isOpen = !!open[s.name];
            return (
              <div className="step" key={s.name}>
                <div className={`step-head ${expandable ? "" : "plain"} ${s.status === "pending" ? "step-pending" : ""}`}
                  onClick={() => expandable && setOpen((o) => ({ ...o, [s.name]: !o[s.name] }))}>
                  {expandable && <span className={`chevron ${isOpen ? "open" : ""}`}>▶</span>}
                  <span className={`step-dot ${s.status}`}>
                    {s.status === "running" ? <span className="spin">◍</span> : DOT[s.status]}
                  </span>
                  <span className="step-num">{s.order}</span>
                  <span className="step-name">{s.name}</span>
                  {s.note && <span className="step-note">· {s.note}</span>}
                  {s.elapsed != null && <span className="step-time">{s.elapsed}s</span>}
                </div>
                {s.metrics && s.metrics.length > 0 && (
                  <div className="metrics">
                    {s.metrics.map((m, i) => (
                      <div className={`metric ${m.kind ?? ""}`} key={i}>
                        <span className="m-label">{m.label}</span>
                        <span className="m-value">{m.value}</span>
                      </div>
                    ))}
                  </div>
                )}
                {expandable && isOpen && (
                  <div className="step-body">
                    <div className="cap">{s.description}</div>
                    <StageBody name={s.name} snap={snap} />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {snap.done && !snap.paused && totalDone > 0 && (
          <div className="banner ok">
            <span className="finished">Pipeline finished — {totalDone}/{snap.total_stages} stages
              {snap.ctx.questions.length ? ` · ${answered}/${snap.ctx.questions.length} intake answers` : ""}. Open any stage to inspect its output.</span>
          </div>
        )}

        {snap.ctx.audit.length > 0 && (
          <>
            <hr className="divider" />
            <h3 style={{ marginBottom: 10 }}>Audit trail <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>(type / version only)</span></h3>
            <div className="tbl-wrap">
              <table>
                <thead><tr><th>time</th><th>actor</th><th>action</th><th>detail</th></tr></thead>
                <tbody>
                  {snap.ctx.audit.map((e, i) => (
                    <tr key={i}>
                      <td className="mono" style={{ whiteSpace: "nowrap" }}>{e.ts.slice(11, 19)}</td>
                      <td>{e.actor}</td>
                      <td className="mono">{e.action}</td>
                      <td className="muted">{e.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
