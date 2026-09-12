// Per-stage result bodies. Mirrors the Streamlit renderers 1:1 so the two UIs
// present identical data — same faithfulness banner, same recovered-value
// notice, same narrative-vs-flags warning.

import type { ReactNode } from "react";
import type { Snapshot } from "./api";
import { fileUrl } from "./api";

function Table({ cols, rows }: { cols: string[]; rows: ReactNode[][] }) {
  return (
    <div className="tbl-wrap">
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StageBody({ name, snap }: { name: string; snap: Snapshot }) {
  const c = snap.ctx;

  if (name === "intake") {
    if (!c.uploads.length) return <p className="muted">No files uploaded.</p>;
    return (
      <div className="grid3">
        {c.uploads.map((u) => {
          const prev = u.processed_path || u.source_path || u.path;
          return (
            <div key={u.id}>
              {prev && <img className="thumb" src={fileUrl(prev)} alt="" />}
              {u.needs_rescan ? (
                <div className="cap" style={{ color: "var(--crit)" }}>
                  ⚠ Rescan · blur {u.blur_score}, brightness {u.brightness}
                </div>
              ) : (
                <div className="cap">OK · blur {u.blur_score ?? "—"}, bright {u.brightness ?? "—"}</div>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  if (name === "ocr") {
    if (!c.ocr) return <p className="muted">No OCR result.</p>;
    const pages = new Set(c.ocr.fields.map((f) => f.page_index).filter((p) => p != null));
    return (
      <div className="two-col">
        <div>
          <div className="cap">
            Extracted fields (⚠ = low confidence)
            {pages.size ? ` · provenance: ${pages.size} page(s)` : ""}
          </div>
          <Table
            cols={["page", "field", "value", "unit", "conf", ""]}
            rows={c.ocr.fields.map((f) => [
              <span className="mono">{f.page_index ?? "—"}</span>,
              f.name,
              <b style={{ color: "var(--ink)" }}>{f.value}</b>,
              f.unit || "",
              <span className="mono">{f.confidence ?? ""}</span>,
              f.low_confidence ? <span style={{ color: "var(--warn)" }}>⚠</span> : "",
            ])}
          />
        </div>
        <div>
          <div className="cap">Raw OCR text</div>
          <div className="raw">{c.ocr.raw_text || "—"}</div>
        </div>
      </div>
    );
  }

  if (name === "image_tag") {
    if (!c.image_tags.length) return <p className="muted">No image tags.</p>;
    const byId: Record<string, any> = {};
    c.image_tags.forEach((t) => (byId[t.upload_id] = t));
    return (
      <>
        <div className="cap">Type + quality only — never a diagnosis (product invariant).</div>
        <div className="grid3">
          {c.uploads.filter((u) => byId[u.id]).map((u) => {
            const t = byId[u.id];
            const prev = u.processed_path || u.source_path || u.path;
            return (
              <div key={u.id}>
                {prev && <img className="thumb" src={fileUrl(prev)} alt="" />}
                <div className="cap">
                  type <code>{t.type}</code> · score {t.score ?? "—"} ·{" "}
                  {t.quality_ok ? "OK" : "⚠ poor"}
                </div>
              </div>
            );
          })}
        </div>
      </>
    );
  }

  if (name === "summary") {
    if (!c.summary) return <p className="muted">No summary.</p>;
    const content = c.summary.content;
    const f = snap.derived.faithfulness;
    const review = snap.derived.narrative_review;
    return (
      <>
        <h4 style={{ marginBottom: 8 }}>स्वास्थ्य सखी रिपोर्ट (draft v{c.summary.version})</h4>
        {f && !f.parse_error && f.ok && (
          <div className="banner ok"><span>✓ Faithfulness {Math.round(f.score * 100)}% — every value traces to OCR.</span></div>
        )}
        {f && !f.parse_error && !f.ok && (
          <div className="banner warn">
            <span>Faithfulness {Math.round(f.score * 100)}% · {f.issues.length} issue(s): {f.issues.slice(0, 4).join("; ")}</span>
          </div>
        )}
        {f?.parse_error && (
          <div className="banner crit"><span>❌ The LLM response could not be parsed ({f.parse_error}). Raw output saved as <code>summary_raw_failed.txt</code>.</span></div>
        )}
        {review.length > 0 && (
          <div className="banner warn">
            <b>⚠ Narrative disagrees with the lab flags — the flags are correct.</b>
            <ul style={{ margin: 0, paddingLeft: 18 }}>{review.map((r, i) => <li key={i}>{r}</li>)}</ul>
            <span style={{ fontSize: 12.5 }}>The narrative is written by the model before the rule-based interpretation runs. Read the flags table as authoritative.</span>
          </div>
        )}
        <div className="two-col" style={{ marginTop: 14 }}>
          <div>
            <div className="cap">Lab findings (source-traced)</div>
            <Table
              cols={["analyte", "value", "unit", "ref range", "source"]}
              rows={(content.lab_findings || []).map((x: any) => [
                x.analyte, <b style={{ color: "var(--ink)" }}>{x.value}</b>, x.unit || "", x.ref_range || "",
                <span className="mono" style={{ fontSize: 11.5 }}>{x.source_field}</span>,
              ])}
            />
            {content.medications?.length > 0 && (
              <><div className="cap">Medications</div><div>{content.medications.map((m: any) => m.name).join(", ")}</div></>
            )}
            {content.unknowns?.length > 0 && (
              <><div className="cap">Unknown / dropped (not in OCR)</div><div className="muted">{content.unknowns.join(", ")}</div></>
            )}
          </div>
          <div>
            <div className="cap">Narrative (English)</div>
            <div className="narrative">{content.narrative_en || "—"}</div>
          </div>
        </div>
      </>
    );
  }

  if (name === "interpret") {
    const mr = snap.derived.maternal_risk;
    if (!c.interpretations.length && !mr) return <p className="muted">No lab flags.</p>;
    const recovered = snap.derived.recovered;
    const tierClass: Record<string, string> = { high: "crit", moderate: "warn", low: "ok", unknown: "info" };
    return (
      <>
        {mr && (
          <div className={`banner ${tierClass[mr.tier] || "info"}`} style={{ display: "block" }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>
              🤰 Maternal risk: {mr.tier_label.toUpperCase()}
              {mr.gestational_age ? ` · ${mr.gestational_age}` : ""}
            </div>
            <div style={{ marginTop: 4 }}><b>Action:</b> {mr.action}</div>
            {mr.red_flags.length > 0 && (
              <div style={{ marginTop: 4 }}>
                <b>Danger signs:</b>
                <ul style={{ margin: "2px 0 0", paddingLeft: 18 }}>
                  {mr.red_flags.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}
            {mr.reasons.length > 0 && (
              <div className="cap" style={{ marginTop: 4 }}>Because: {mr.reasons.join(" · ")}</div>
            )}
            <div className="cap" style={{ marginTop: 4, opacity: 0.8 }}>
              Rule-based triage from maternal thresholds — a risk STATUS, not a diagnosis. Thresholds pending clinician review.
            </div>
          </div>
        )}
        {snap.derived.narrative_review.length > 0 && (
          <div className="banner warn">
            <b>⚠ Narrative disagrees with the lab flags — the flags are correct.</b>
            <ul style={{ margin: 0, paddingLeft: 18 }}>{snap.derived.narrative_review.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
        )}
        {recovered.length > 0 && (
          <div className="banner info">
            <span><b>ℹ {recovered.length} value(s) recovered from OCR:</b> {recovered.join(", ")} — read by OCR but missing from the summary model's findings. Flagged so an LLM omission cannot hide a value from the doctor.</span>
          </div>
        )}
        <div style={{ marginTop: 12 }}>
          <Table
            cols={["analyte", "value", "unit", "ref range", "status", "priority"]}
            rows={c.interpretations.map((x: any) => [
              x.analyte, <b style={{ color: "var(--ink)" }}>{x.value}</b>, x.unit || "", x.ref_range || "",
              <span className={`pill ${x.status}`}>{x.status}</span>,
              x.high_priority ? <span className="dot-hi">🔴</span> : "",
            ])}
          />
        </div>
      </>
    );
  }

  if (name === "intake_qa") {
    if (!c.questions.length) return <p className="muted">No questions generated.</p>;
    const ans: Record<string, any> = {};
    c.answers.forEach((a) => (ans[a.question_id] = a));
    return (
      <>
        <div className="cap">Grounded intake questions (template-fill). Live speak-and-record arrives in the next build.</div>
        {c.questions.map((q) => (
          <div key={q.id} style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 600, color: "var(--ink)" }}>Q ({q.lang}): {q.rendered_text}</div>
            <div className="cap" style={{ marginTop: 2 }}>
              {ans[q.id]?.transcript ? `↳ ${ans[q.id].transcript}` : "↳ — (no answer)"}
            </div>
          </div>
        ))}
      </>
    );
  }

  if (name === "voice") {
    if (!c.audio_out.length) return <p className="muted">No audio generated.</p>;
    return (
      <>
        {c.audio_out.map((clip) => (
          <div key={clip.id} style={{ marginBottom: 10 }}>
            <div className="cap"><code>{clip.id}</code> · {clip.kind} · {clip.lang}{clip.duration_ms ? ` · ${clip.duration_ms} ms` : ""}</div>
            {clip.path && <audio controls src={fileUrl(clip.path)} controlsList="nodownload" />}
          </div>
        ))}
      </>
    );
  }

  if (name === "hashing") {
    const rows = c.uploads.map((u: any) => [
      (u.path || "").split(/[\\/]/).pop(),
      <span className="mono">{(u.sha256 || "—").slice(0, 16)}</span>,
    ]);
    if (c.report?.sha256) rows.push([`report v${c.report.version}`, <span className="mono">{c.report.sha256.slice(0, 16)}</span>]);
    return <Table cols={["file", "sha256"]} rows={rows} />;
  }

  if (name === "report") {
    if (!c.report) return <p className="muted">No final report.</p>;
    return (
      <>
        <div className="cap">Report v{c.report.version}{c.report.sha256 ? ` · sha ${c.report.sha256.slice(0, 16)}` : ""}</div>
        <div className="raw">{JSON.stringify(c.report.content, null, 2)}</div>
      </>
    );
  }

  return <p className="muted">—</p>;
}
