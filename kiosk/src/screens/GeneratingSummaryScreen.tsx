import { useEffect, useRef, useState } from "react";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { ProcessingAnimation } from "../components/ProcessingAnimation";
import { ProgressSteps, type Step } from "../components/ProgressSteps";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";
import { usePipeline } from "../state/PipelineContext";

const MAX_WAIT = 15000; // safety net if sealing stalls

export function GeneratingSummaryScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();
  const { finalize } = usePipeline();
  const [activeIndex, setActiveIndex] = useState(3);
  const started = useRef(false);

  // Seal the report (resume past the Q&A gate → hashing + report), then show it.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const safety = setTimeout(() => kiosk.summaryReady(), MAX_WAIT);
    finalize()
      .catch(() => { /* summary already exists; show it regardless */ })
      .finally(() => {
        clearTimeout(safety);
        setTimeout(() => kiosk.summaryReady(), 400);
      });
    return () => clearTimeout(safety);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const stepTimer = setInterval(() => setActiveIndex((i) => Math.min(i + 1, 5)), 900);
    return () => clearInterval(stepTimer);
  }, []);

  const steps: Step[] = [
    { label: t("stepReportReceived"), status: "done" },
    { label: t("stepResponsesReceived"), status: "done" },
    { label: t("stepFindingsIdentified"), status: "done" },
    { label: t("stepPreparingSummary"), status: activeIndex > 3 ? "done" : "active" },
    { label: t("stepSendingToDoctor"), status: activeIndex > 4 ? "done" : activeIndex === 4 ? "active" : "pending" },
  ];

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state="processing" size={100} />
          <AvatarSpeechBubble text={t("avatarGeneratingSummary")} />
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-6 py-2 text-center">
        <ProcessingAnimation />
        <div className="w-full max-w-xs rounded-2xl bg-white p-4 text-left shadow-sm">
          <ProgressSteps steps={steps} />
        </div>
      </div>
    </KioskLayout>
  );
}
