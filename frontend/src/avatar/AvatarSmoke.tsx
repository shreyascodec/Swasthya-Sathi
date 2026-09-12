// Phase-A/B/C browser smoke: mesh + live TTS + precomputed clip + Hindi cues.
import { useState, type CSSProperties } from "react";
import { AvatarScene } from "./AvatarScene";
import { AvatarBoundary } from "./AvatarBoundary";
import { useAvatarTTS } from "./useAvatarTTS";
import { detectExpression } from "./expressions";

const SAMPLE_HI = "नमस्ते, मैं आपकी रिपोर्ट समझाने में मदद करूँगा।";
const SAMPLE_EN = "Hello, I will help explain your report.";
const SAMPLE_THINK_HI = "कृपया बताइए, क्या आप कोई दवा ले रहे हैं?";

export function AvatarSmoke() {
  const { speak, speakClip, stop, speaking, amplitude, visemeRef, expressionRef } = useAvatarTTS();
  const [log, setLog] = useState<string>("Ready — A live · B precompute · C expression.");

  async function runLive(text: string, lang: string) {
    setLog(`Phase A: live TTS (${lang})…`);
    await speak(text, lang);
    setLog(`Phase A: speaking (${lang}). Watch mouth / jaw.`);
  }

  async function runPrecomputed(text: string, lang: string) {
    setLog(`Phase B: synthesizing once + writing clip…`);
    try {
      const res = await fetch("/api/avatar/smoke-clip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, lang }),
      });
      if (!res.ok) throw new Error(`smoke-clip ${res.status}`);
      const clip = await res.json();
      setLog(`Phase B: replaying clip (${clip.alignment?.length ?? 0} phonemes)…`);
      await speakClip({ path: clip.path, alignment: clip.alignment, text });
      setLog(`Phase B OK: replayed precomputed voice (${lang}).`);
    } catch (e) {
      setLog(`Phase B failed: ${String(e)}`);
    }
  }

  async function runClinicCue() {
    const expr = detectExpression(SAMPLE_THINK_HI, "thinking");
    setLog(`Phase C: cue=${expr} · speaking Hindi question…`);
    await speak(SAMPLE_THINK_HI, "hi");
    // Expression resets to neutral when speech ends; capture mid-speak via ref
    // before onended. Poll briefly while speaking.
    await new Promise((r) => setTimeout(r, 400));
    const live = expressionRef.current;
    setLog(`Phase C OK: detect=${expr} liveExpr=${live} (expect thinking).`);
  }

  return (
    <div style={{ minHeight: "100vh", background: "#1a2836", color: "#e8eef4", padding: 24, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ margin: "0 0 8px", fontSize: 22 }}>Avatar smoke (Phase A / B / C)</h1>
      <p style={{ margin: "0 0 16px", opacity: 0.8, fontSize: 14 }}>
        Mesh · live TTS · precomputed clip · Hindi expression cues
      </p>
      <div style={{ height: 420, borderRadius: 12, overflow: "hidden", border: "1px solid #3a556e" }}>
        <AvatarBoundary>
          <AvatarScene
            speaking={speaking}
            listening={false}
            amplitude={amplitude}
            visemeRef={visemeRef}
            expressionRef={expressionRef}
          />
        </AvatarBoundary>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap" }}>
        <button type="button" disabled={speaking} onClick={() => runLive(SAMPLE_HI, "hi")} style={btn}>
          A · Speak Hindi (live)
        </button>
        <button type="button" disabled={speaking} onClick={() => runLive(SAMPLE_EN, "en")} style={btn}>
          A · Speak English (live)
        </button>
        <button
          type="button"
          disabled={speaking}
          onClick={() => runPrecomputed(SAMPLE_HI, "hi")}
          style={{ ...btn, background: "#1f8a5b" }}
        >
          B · Precompute &amp; replay Hindi
        </button>
        <button
          type="button"
          disabled={speaking}
          onClick={() => runClinicCue()}
          style={{ ...btn, background: "#8a5a1f" }}
        >
          C · Hindi thinking cue
        </button>
        {speaking && (
          <button type="button" onClick={stop} style={{ ...btn, background: "#8b3a3a" }}>
            Stop
          </button>
        )}
        <a href="/" style={{ ...btn, textDecoration: "none", display: "inline-flex", alignItems: "center" }}>
          ← Back to kiosk
        </a>
      </div>
      <p style={{ marginTop: 14, fontSize: 14 }}>{log}</p>
    </div>
  );
}

const btn: CSSProperties = {
  background: "#2f6fed",
  color: "#fff",
  border: "none",
  borderRadius: 8,
  padding: "10px 16px",
  fontSize: 14,
  cursor: "pointer",
};
