import { useEffect, useRef, useState } from "react";
import { api, type Readiness, type Snapshot, type StageInfo } from "./api";
import { StageBody } from "./StageBody";
import { LiveQA } from "./LiveQA";

// code -> [native label, latin label]. Values stay ISO codes (backend expects "hi").
const LANGS: [string, string, string][] = [
  ["hi", "हिन्दी", "Hindi"],
  ["en", "English", "English"],
  ["mr", "मराठी", "Marathi"],
  ["bn", "বাংলা", "Bengali"],
  ["ta", "தமிழ்", "Tamil"],
  ["te", "తెలుగు", "Telugu"],
];
// Only these are built/verified today; the rest are shown but greyed + crossed out.
const AVAILABLE_LANGS = new Set(["hi", "en"]);

// Friendlier stage titles. Falls back to the backend name if a code is unknown.
const STAGE_LABEL: Record<string, string> = {
  intake: "Intake & image quality",
  ocr: "Text extraction (OCR)",
  image_tag: "Image tagging",
  summary: "Report summary",
  interpret: "Lab interpretation",
  intake_qa: "Intake questions",
  voice: "Voice generation",
  hashing: "Integrity hashing",
  report: "Final report",
};
const DOT: Record<string, string> = { done: "✓", flagged: "!", error: "✕", running: "", pending: "" };

// Short labels + icons + present-tense verbs for the horizontal processing view.
const STAGE_SHORT: Record<string, string> = {
  intake: "Intake", ocr: "OCR", image_tag: "Tag", summary: "Summary",
  interpret: "Interpret", intake_qa: "Questions", voice: "Voice",
  hashing: "Hashing", report: "Report",
};
const STAGE_ICON: Record<string, string> = {
  intake: "🖼️", ocr: "🔤", image_tag: "🏷️", summary: "📝", interpret: "🩺",
  intake_qa: "❓", voice: "🔊", hashing: "🔐", report: "📄",
};
const STAGE_DOING: Record<string, string> = {
  intake: "Checking image quality…", ocr: "Reading the report text…",
  image_tag: "Tagging clinical images…", summary: "Writing the summary…",
  interpret: "Scoring maternal risk…", intake_qa: "Preparing danger-sign questions…",
  voice: "Creating the voice explanation…", hashing: "Sealing & hashing…",
  report: "Assembling the final report…",
};

// Stages hidden from the UI (they STILL RUN in the backend — this is display-only,
// for testing). Empty the set to show everything again.
const HIDDEN_STAGES = new Set<string>([]);
const visibleStages = (snap: Snapshot): StageInfo[] => snap.stages.filter((s) => !HIDDEN_STAGES.has(s.name));

// The stage the focused card + rail marker point at: the running one, else the
// paused one, else the next pending one — skipping hidden stages.
function activeStageName(snap: Snapshot): string | null {
  const vis = visibleStages(snap);
  const run = vis.find((s) => s.status === "running");
  if (run) return run.name;
  if (snap.paused && !HIDDEN_STAGES.has(snap.paused.stage)) return snap.paused.stage;
  if (!snap.done) return vis.find((s) => s.status !== "done" && s.status !== "flagged")?.name ?? null;
  return null;
}

function fmtBytes(n: number) {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

type Phase = "welcome" | "upload" | "run";

// Where a reattached session should resume: mid/after a run → the run screen,
// files uploaded but not started → upload, otherwise the welcome screen.
function phaseFor(s: Snapshot): Phase {
  const started = s.stages.some((st) => ["done", "flagged", "error", "running"].includes(st.status));
  if (s.done || s.paused || started) return "run";
  if (s.ctx.uploads.length) return "upload";
  return "welcome";
}

export default function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [phase, setPhase] = useState<Phase>("welcome");
  const [lang, setLang] = useState("hi");
  const [staged, setStaged] = useState<File[]>([]);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [over, setOver] = useState(false);
  // Transport-level failure (backend down, session lost after a restart). Shown
  // as an inline banner, never alert(): a modal on a kiosk blocks the whole
  // screen until someone finds a keyboard to dismiss it.
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState<Readiness | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // First load: reattach to a still-live session if this browser has one (a
  // refresh must not orphan the patient's in-progress run), else start fresh.
  useEffect(() => {
    const saved = sessionStorage.getItem("ss_sid");
    const boot = saved
      ? api.getSession(saved).catch(() => api.createSession(lang))
      : api.createSession(lang);
    boot.then((s) => {
      setSnap(s); setLang(s.lang);
      const ph = phaseFor(s);
      setPhase(ph);
      // Reattached mid-run (a reload during processing): keep driving the stages
      // so the run finishes instead of stalling on a dead client loop.
      if (ph === "run" && !s.done && !s.paused) {
        setRunning(true);
        driveStages(s).catch((e) => setErr(String(e))).finally(() => setRunning(false));
      }
    }).catch((e) => setErr(`Backend not reachable. ${e}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Remember the active session id so a reload can reattach to it.
  useEffect(() => {
    if (snap) sessionStorage.setItem("ss_sid", snap.session_id);
  }, [snap?.session_id]);

  // Poll readiness until the models are warm (then stop). The kiosk holds the
  // Process button until this reports ready so the first patient isn't slow.
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const r = await api.getReady();
        if (stop) return;
        setReady(r);
        if (r.ready) return; // warm — stop polling
      } catch { /* backend not up yet; keep trying */ }
      if (!stop) timer = setTimeout(tick, 1500);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, []);

  async function newSession(l = lang) {
    setStaged([]); setOpen({}); setRunning(false); setErr(null);
    const s = await api.createSession(l);
    setSnap(s);
  }

  async function pickLang(l: string) {
    setLang(l);
    if (l !== snap?.lang) await newSession(l);
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    setStaged((prev) => [...prev, ...Array.from(list)]);
  }

  // Drive the stage loop one call at a time — mirrors the Streamlit stepper.
  // Shared by process(), resume(), and reattach so all three continue a run the
  // same way.
  async function driveStages(start: Snapshot) {
    let s = start;
    while (!s.done && !s.paused) {
      const nextName = s.stages[s.next_idx]?.name;
      if (nextName) {
        setSnap({ ...s, stages: s.stages.map((st) => st.name === nextName ? { ...st, status: "running" } : st) });
      }
      s = await api.runStage(s.session_id);
      setSnap(s);
    }
    return s;
  }

  async function process() {
    if (!snap) return;
    setPhase("run");
    setRunning(true);
    setErr(null);
    try {
      let s = staged.length ? await api.upload(snap.session_id, staged) : snap;
      setSnap(s); setStaged([]);
      await driveStages(s);
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
    try {
      const s = await api.resume(snap.session_id, action);
      setSnap(s);
      if (action === "stop") return;
      await driveStages(s);
    } catch (e) {
      setErr(String(e));
    } finally { setRunning(false); }
  }

  if (!snap) {
    return (
      <div className="app">
        <div className="welcome">
          <div className="welcome-inner">
            <div className="welcome-mark">📋</div>
            <p className="muted"><span className="spin">◍</span> Connecting to pipeline…</p>
            {err && <div className="banner crit" style={{ marginTop: 20, textAlign: "left" }}><b>✕ {err}</b></div>}
          </div>
        </div>
      </div>
    );
  }

  const inQA = phase === "run" && snap.paused?.kind === "intake_qa";
  const totalDone = visibleStages(snap).filter((s) => s.status === "done" || s.status === "flagged").length;
  const visTotal = visibleStages(snap).length;
  const finished = phase === "run" && snap.done && !snap.paused && totalDone > 0;
  const answered = snap.ctx.answers.length;
  // Treat "unknown" as ready so a failed /ready poll never deadlocks the kiosk.
  const modelsReady = !ready || ready.ready;
  const warming = !!ready && !ready.ready;

  // Which rail step is active (Upload · Process · Questions · Report).
  const railActive = phase === "upload" ? 0 : inQA ? 2 : finished ? 3 : 1;

  return (
    <div className="app">
      {/* ---------- persistent app bar ---------- */}
      <header className="appbar">
        <div className="brand" onClick={() => { setPhase("welcome"); }} style={{ cursor: "pointer" }}>
          <span className="brand-mark">📋</span>
          <span className="brand-txt">
            <span className="brand-hi">स्वास्थ्य सखी</span>
            <span className="brand-en">Swasthya Sakhi · Maternal health</span>
          </span>
        </div>
        <div className="bar-spacer" />
        <div className="chips">
          {warming && <span className="chip warming"><span className="spin">◍</span> Warming up…</span>}
          {running && <span className="chip live"><span className="live-dot" /> Processing</span>}
          <span className="chip"><span className="k">Env</span><span className="v">{snap.env} · {snap.device}</span></span>
          <span className="chip"><span className="k">Session</span><span className="v">{snap.session_id.slice(0, 8)}</span></span>
        </div>
      </header>

      <div className="canvas">
        {phase === "welcome" && (
          <Welcome
            lang={lang}
            running={running}
            onPick={pickLang}
            onStart={() => setPhase("upload")}
          />
        )}

        {phase !== "welcome" && (
          <div className={`page ${phase === "run" && finished ? "page-wide" : ""}`}>
            <Rail active={railActive} />

            {err && (
              <div className="banner crit fade-in">
                <b>✕ Could not reach the pipeline</b>
                <span>{err}</span>
                <div className="actions">
                  <button className="btn-ghost" onClick={() => { setErr(null); setPhase("welcome"); newSession(); }}>Start over</button>
                  <button className="btn-ghost" onClick={() => setErr(null)}>Dismiss</button>
                </div>
              </div>
            )}

            {/* ---------- UPLOAD ---------- */}
            {phase === "upload" && (
              <div className="fade-in">
                <div className="page-head">
                  <h2>Upload the ANC card or report</h2>
                  <p>Add photos or a PDF of the antenatal card / lab report. You can add more than one page.</p>
                </div>

                <div
                  className={`drop ${over ? "over" : ""}`}
                  onClick={() => fileInput.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setOver(true); }}
                  onDragLeave={() => setOver(false)}
                  onDrop={(e) => { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files); }}
                >
                  <div className="drop-icon">🖼️</div>
                  <h3>Tap to choose files, or drag them here</h3>
                  <p className="formats">JPG · PNG · BMP · TIFF · WEBP · PDF</p>
                  <button className="btn-ghost" onClick={(e) => { e.stopPropagation(); fileInput.current?.click(); }}>Browse files</button>
                  <input ref={fileInput} type="file" hidden multiple
                    accept=".jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp,.pdf"
                    onChange={(e) => addFiles(e.target.files)} />
                </div>

                {(staged.length > 0 || snap.ctx.uploads.length > 0) && (
                  <div className="file-list">
                    {staged.map((f, i) => (
                      <div className="file-row" key={i}>
                        <span className="fi">📄</span>
                        <span className="name">{f.name}</span>
                        <span className="size">{fmtBytes(f.size)}</span>
                        <button className="x" onClick={() => setStaged((p) => p.filter((_, j) => j !== i))} aria-label="Remove">✕</button>
                      </div>
                    ))}
                    {staged.length === 0 && snap.ctx.uploads.length > 0 && (
                      <p className="muted" style={{ fontSize: 14 }}>This session already has {snap.ctx.uploads.length} uploaded file(s) — press Process to run them.</p>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ---------- RUN: Q&A takes over the screen when the pipeline pauses for it ---------- */}
            {inQA && (
              <div className="qa-shell fade-in">
                <LiveQA snap={snap} onSnap={setSnap} onContinue={() => resume("continue")} />
              </div>
            )}

            {/* ---------- RUN: processing (horizontal) / results (detailed) ---------- */}
            {phase === "run" && !inQA && (
              <div className="fade-in">
                {/* ===== still running / paused at a gate: horizontal focused view ===== */}
                {!finished && (
                  <>
                    <div className="proc-head">
                      <div>
                        <h2>{running ? "Processing the report…" : snap.paused ? "Action needed" : "Processing…"}</h2>
                        <p className="muted">{running ? "Please wait — this only takes a moment." : "Resolve the step below to continue."}</p>
                      </div>
                      <div className="proc-count">{totalDone}<span>/{visTotal}</span></div>
                    </div>

                    <StepperRail snap={snap} />

                    {/* Quality / error / parse gates (not the intake-Q&A gate). */}
                    {snap.paused && snap.paused.kind !== "intake_qa" ? (
                      <div className={`gate ${snap.paused.kind === "error" ? "crit" : "warn"} fade-in`}>
                        <div className="gate-title">
                          {snap.paused.kind === "error" ? "✕" : "⚠"} Paused after “{STAGE_LABEL[snap.paused.stage] ?? snap.paused.stage}”
                        </div>
                        <div className="gate-detail">{snap.paused.detail}</div>
                        <div className="actions">
                          {snap.paused.kind === "error"
                            ? <button className="btn-warn btn-lg" onClick={() => resume("retry")}>↻ Retry stage</button>
                            : <button className="btn-primary btn-lg" onClick={() => resume("continue")}>Continue ▶</button>}
                          <button className="btn-ghost btn-lg" onClick={() => resume("stop")}>Stop</button>
                        </div>
                      </div>
                    ) : (
                      <FocusCard snap={snap} running={running} />
                    )}
                  </>
                )}

                {/* ===== finished: the detailed, inspectable view ===== */}
                {finished && (
                  <>
                    <ResultHero snap={snap} totalDone={totalDone} answered={answered} />
                    <div className="section-title">Pipeline stages · {totalDone}/{visTotal}</div>
                    <Timeline snap={snap} open={open} setOpen={setOpen} />

                    {snap.ctx.audit.length > 0 && (
                      <>
                        <div className="section-title">Audit trail</div>
                        <details className="disclosure">
                          <summary><span className="chevron">▶</span> {snap.ctx.audit.length} events <span className="muted" style={{ fontWeight: 400 }}>· type / version only</span></summary>
                          <div className="disc-body">
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
                          </div>
                        </details>
                      </>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ---------- sticky action dock ---------- */}
      {phase === "upload" && (
        <div className="dock">
          <div className="dock-inner">
            <button className="btn-ghost btn-lg" onClick={() => setPhase("welcome")}>← Back</button>
            {warming && <span className="muted" style={{ fontSize: 14 }}><span className="spin">◍</span> Warming up models — one moment…</span>}
            <div className="spacer" />
            <button className="btn-primary btn-lg" onClick={process}
              disabled={running || !modelsReady || (!staged.length && !snap.ctx.uploads.length)}>
              {warming ? "Warming up…" : `Process${staged.length ? ` ${staged.length} file(s)` : ""} ▶`}
            </button>
          </div>
        </div>
      )}
      {finished && (
        <div className="dock">
          <div className="dock-inner">
            <button className="btn-primary btn-lg btn-block" onClick={() => { setPhase("welcome"); newSession(); }}>
              ✓ Done — start next patient
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================================================ Welcome */
function Welcome({ lang, running, onPick, onStart }: {
  lang: string; running: boolean; onPick: (l: string) => void; onStart: () => void;
}) {
  return (
    <div className="welcome fade-in">
      <div className="welcome-inner">
        <div className="welcome-mark">📋</div>
        <h1>स्वास्थ्य सखी</h1>
        <div className="en-name">Swasthya Sakhi</div>
        <p className="tag">Maternal health risk screening. Upload an ANC card or antenatal report — we flag risk and ask danger-sign questions in her language.</p>

        <div className="prompt">Choose your language · अपनी भाषा चुनें</div>
        <div className="lang-grid">
          {LANGS.map(([code, native, latin]) => {
            const avail = AVAILABLE_LANGS.has(code);
            return (
              <button key={code}
                className={`lang-card ${lang === code && avail ? "sel" : ""} ${avail ? "" : "unavail"}`}
                onClick={() => avail && onPick(code)}
                disabled={running || !avail}
                aria-disabled={!avail}
                title={avail ? undefined : `${latin} — coming soon`}>
                <span className="native">{native}</span>
                <span className="latin">{latin} {lang === code && avail && <span className="tick">✓</span>}</span>
                {!avail && <span className="soon">soon</span>}
              </button>
            );
          })}
        </div>

        <div style={{ marginTop: 34 }}>
          <button className="btn-primary btn-lg" style={{ minWidth: 240 }} onClick={onStart} disabled={running}>
            Start →
          </button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================ Flow rail */
function Rail({ active }: { active: number }) {
  const steps = ["Upload", "Process", "Questions", "Report"];
  return (
    <div className="rail">
      {steps.map((label, i) => (
        <RailSeg key={label} label={label} n={i + 1} state={i < active ? "done" : i === active ? "active" : "todo"} first={i === 0} filled={i < active} />
      ))}
    </div>
  );
}
function RailSeg({ label, n, state, first, filled }: { label: string; n: number; state: string; first: boolean; filled: boolean }) {
  return (
    <>
      {!first && <div className={`rail-line ${filled ? "filled" : ""}`} />}
      <div className={`rail-step ${state}`}>
        <span className="rail-num">{state === "done" ? "✓" : n}</span>
        <span className="rail-label">{label}</span>
      </div>
    </>
  );
}

/* ============================================================ Result hero */
function ResultHero({ snap, totalDone, answered }: { snap: Snapshot; totalDone: number; answered: number }) {
  const f = snap.derived.faithfulness;
  const flags = snap.ctx.interpretations.filter((x: any) => x.status && x.status !== "normal").length;
  return (
    <div className="result-hero fade-in">
      <div className="seal">✓</div>
      <div style={{ minWidth: 0 }}>
        <h2>Maternal risk report ready</h2>
        <p>All {totalDone} stages complete{snap.ctx.report?.version ? ` · report v${snap.ctx.report.version}` : ""}. Open Interpret for the risk tier, then inspect the other stages.</p>
      </div>
      <div className="result-stats">
        {f && !f.parse_error && (
          <div className="rstat"><div className="n">{Math.round(f.score * 100)}%</div><div className="l">Faithful</div></div>
        )}
        <div className="rstat"><div className="n">{snap.ctx.interpretations.length}</div><div className="l">Analytes</div></div>
        <div className="rstat"><div className="n" style={{ color: flags ? "var(--warn)" : undefined }}>{flags}</div><div className="l">Flagged</div></div>
        {snap.ctx.questions.length > 0 && (
          <div className="rstat"><div className="n">{answered}/{snap.ctx.questions.length}</div><div className="l">Answers</div></div>
        )}
      </div>
    </div>
  );
}

/* ============================================================ Stage timeline */
function Timeline({ snap, open, setOpen }: {
  snap: Snapshot; open: Record<string, boolean>; setOpen: (f: (o: Record<string, boolean>) => Record<string, boolean>) => void;
}) {
  return (
    <div className="timeline">
      {visibleStages(snap).map((s: StageInfo) => {
        const expandable = s.status === "done" || s.status === "flagged";
        const isOpen = !!open[s.name];
        return (
          <div className={`tl-step ${s.status}`} key={s.name}>
            <span className={`tl-dot ${s.status}`}>
              {s.status === "running" ? <span className="spin">◍</span> : (DOT[s.status] || s.order)}
            </span>
            <div className="tl-card">
              <div className={`tl-head ${expandable ? "clickable" : ""}`}
                onClick={() => expandable && setOpen((o) => ({ ...o, [s.name]: !o[s.name] }))}>
                {expandable && <span className={`chevron ${isOpen ? "open" : ""}`}>▶</span>}
                <span className="tl-name">{STAGE_LABEL[s.name] ?? s.name}</span>
                {s.note && <span className="tl-note">· {s.note}</span>}
                {s.elapsed != null && <span className="tl-time">{s.elapsed}s</span>}
              </div>
              {s.metrics && s.metrics.length > 0 && (
                <div className="tl-metrics">
                  {s.metrics.map((m, i) => (
                    <div className={`metric ${m.kind ?? ""}`} key={i}>
                      <span className="m-label">{m.label}</span>
                      <span className="m-value">{m.value}</span>
                    </div>
                  ))}
                </div>
              )}
              {expandable && isOpen && (
                <div className="tl-body">
                  {s.description && <div className="cap">{s.description}</div>}
                  <StageBody name={s.name} snap={snap} />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ============================================================ Horizontal processing view */
function StepperRail({ snap }: { snap: Snapshot }) {
  const activeName = activeStageName(snap);
  const anyRunning = snap.stages.some((s) => s.status === "running");
  return (
    <div className="srail" role="list" aria-label="Pipeline progress">
      {visibleStages(snap).map((s: StageInfo, i: number) => {
        const done = s.status === "done" || s.status === "flagged";
        const isActive = !snap.done && s.name === activeName;
        const cls = done ? "done" : s.status === "error" ? "error" : isActive ? "active" : "todo";
        return (
          <div className={`srail-step ${cls}`} key={s.name} role="listitem" title={STAGE_LABEL[s.name] ?? s.name}>
            <span className="srail-node">
              {s.status === "done" ? "✓"
                : s.status === "flagged" ? "!"
                : s.status === "error" ? "✕"
                : isActive && anyRunning ? <span className="spin">◍</span>
                : i + 1}
            </span>
            <span className="srail-label">{STAGE_SHORT[s.name] ?? s.name}</span>
          </div>
        );
      })}
    </div>
  );
}

function FocusCard({ snap, running }: { snap: Snapshot; running: boolean }) {
  const name = activeStageName(snap);
  const vis = visibleStages(snap);
  const idx = name ? vis.findIndex((x) => x.name === name) : -1;
  const s = idx >= 0 ? vis[idx] : null;
  if (!s) return null;
  const isErr = s.status === "error";
  const isFlag = s.status === "flagged";
  const busy = running || s.status === "running";
  const status = isErr ? "This step failed."
    : isFlag ? "Flagged for review."
    : busy ? (STAGE_DOING[s.name] ?? "Working…")
    : "Starting…";
  return (
    <div className={`focus-card ${isErr ? "err" : isFlag ? "flag" : ""} fade-in`}>
      <div className="focus-icon">{STAGE_ICON[s.name] ?? "•"}</div>
      <div className="focus-body">
        <div className="focus-title">{STAGE_LABEL[s.name] ?? s.name}</div>
        <div className="focus-status">
          {busy && !isErr && !isFlag && <span className="spin">◍</span>}{status}
        </div>
        {s.metrics && s.metrics.length > 0 && (
          <div className="focus-metrics">
            {s.metrics.map((m, i) => (
              <div className={`metric ${m.kind ?? ""}`} key={i}>
                <span className="m-label">{m.label}</span>
                <span className="m-value">{m.value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="focus-step">Step {idx + 1}<span> of {vis.length}</span></div>
      {busy && !isErr && !isFlag && <div className="focus-bar"><span /></div>}
    </div>
  );
}
