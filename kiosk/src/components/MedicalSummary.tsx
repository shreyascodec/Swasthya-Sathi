import { useLanguage } from "../i18n/LanguageContext";
import { usePipeline } from "../state/PipelineContext";
import type { RiskTier } from "../api/client";

const tierStyle: Record<RiskTier, { bg: string; border: string; text: string; dot: string }> = {
  high: { bg: "bg-danger/10", border: "border-danger/40", text: "text-danger", dot: "bg-danger" },
  moderate: { bg: "bg-warning/10", border: "border-warning/40", text: "text-[#966a10]", dot: "bg-warning" },
  low: { bg: "bg-success/10", border: "border-success/40", text: "text-success", dot: "bg-success" },
  unknown: { bg: "bg-mint", border: "border-mint-2", text: "text-text-secondary", dot: "bg-text-secondary" },
};

function statusSeverity(status: string): "normal" | "attention" | "important" {
  const s = (status || "").toLowerCase();
  if (s === "critical") return "important";
  if (s === "high" || s === "low") return "attention";
  return "normal";
}
const sevStyle = {
  normal: { bg: "bg-success/10", text: "text-success", dot: "bg-success" },
  attention: { bg: "bg-warning/10", text: "text-[#966a10]", dot: "bg-warning" },
  important: { bg: "bg-danger/10", text: "text-danger", dot: "bg-danger" },
};

export function MedicalSummary() {
  const { t } = useLanguage();
  const { maternalRisk, snapshot } = usePipeline();

  if (!maternalRisk || maternalRisk.tier === "unknown") {
    return (
      <div className="rounded-2xl bg-white p-4 text-center text-sm text-text-secondary shadow-sm">
        {t("summaryEmpty")}
      </div>
    );
  }

  const tier = maternalRisk.tier;
  const ts = tierStyle[tier];
  const tierLabel = t(`risk_${tier}` as any);
  const tierAction = t(`action_${tier}` as any);
  const answers = snapshot?.ctx.answers || [];

  return (
    <div className="space-y-4">
      {/* Risk tier banner */}
      <div className={`rounded-2xl border-2 ${ts.border} ${ts.bg} p-4`}>
        <p className="text-[11px] font-bold uppercase tracking-wide text-text-secondary">{t("riskAssessment")}</p>
        <div className="mt-1 flex items-center gap-2">
          <span className={`h-3 w-3 rounded-full ${ts.dot}`} />
          <span className={`text-xl font-extrabold ${ts.text}`}>{tierLabel}</span>
          {maternalRisk.gestational_age && (
            <span className="ml-auto text-xs font-semibold text-text-secondary">{maternalRisk.gestational_age}</span>
          )}
        </div>
        <p className="mt-2 text-sm font-semibold leading-snug text-text-primary">{tierAction}</p>
      </div>

      {/* Red flags */}
      {maternalRisk.red_flags.length > 0 && (
        <div className="rounded-2xl border-2 border-danger/25 bg-danger/5 p-4">
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-danger">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M12 9v4m0 4h.01M10.29 3.86l-8.18 14.18A1.5 1.5 0 0 0 3.5 20h17a1.5 1.5 0 0 0 1.39-1.96L13.71 3.86a1.5 1.5 0 0 0-2.42 0Z"
                stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t("redFlags")}
          </p>
          <ul className="space-y-1">
            {maternalRisk.red_flags.map((r, i) => (
              <li key={i} className="text-xs font-medium text-text-primary">• {r}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Measured values */}
      {maternalRisk.parameters.length > 0 && (
        <div className="rounded-2xl bg-white p-4 shadow-sm">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-text-secondary">{t("measuredValues")}</p>
          <div className="grid grid-cols-2 gap-2">
            {maternalRisk.parameters.map((p, i) => {
              const s = sevStyle[statusSeverity(p.status)];
              return (
                <div key={i} className={`rounded-xl ${s.bg} p-2.5`}>
                  <div className="flex items-center gap-1.5">
                    <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
                    <p className="text-[10px] font-medium text-text-secondary">{p.name}</p>
                  </div>
                  <p className={`mt-0.5 text-sm font-bold ${s.text}`}>{p.value || "—"}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Danger-sign responses (real transcripts) */}
      {answers.length > 0 && (
        <div className="rounded-2xl bg-white p-4 shadow-sm">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-text-secondary">{t("dangerResponses")}</p>
          <div className="flex flex-col gap-2">
            {answers.map((a, i) => {
              const q = (snapshot?.ctx.questions || []).find((qq) => qq.id === a.question_id);
              const flagged = maternalRisk.danger_signs.find((d) => d.question === q?.rendered_text)?.flag;
              return (
                <div key={i} className={`rounded-xl px-3 py-2 ${flagged ? "bg-danger/5 border border-danger/25" : "bg-mint"}`}>
                  <p className="text-[11px] font-medium text-text-secondary">{q?.rendered_text || t("answerRecorded")}</p>
                  <p className={`text-sm font-semibold ${flagged ? "text-danger" : "text-text-primary"}`}>{a.transcript || "—"}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <p className="px-1 text-center text-[11px] leading-relaxed text-text-secondary">{t("mchDisclaimer")}</p>
    </div>
  );
}
