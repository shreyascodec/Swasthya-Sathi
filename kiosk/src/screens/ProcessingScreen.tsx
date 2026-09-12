import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { ProcessingAnimation } from "../components/ProcessingAnimation";
import { ProgressSteps, type Step } from "../components/ProgressSteps";
import { PrimaryButton } from "../components/PrimaryButton";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";
import { usePipeline } from "../state/PipelineContext";

const STEP_DURATION = 1100;

export function ProcessingScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();
  const { driveProcessing } = usePipeline();
  const [activeIndex, setActiveIndex] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const statusTexts = [t("statusReading"), t("statusExtracting"), t("statusOrganizing"), t("statusPreparing")];
  const [statusIndex, setStatusIndex] = useState(0);

  // Drive the real pipeline once. The visual step/status animation is cosmetic;
  // the SCREEN only advances on the actual backend outcome.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      const outcome = await driveProcessing();
      if (outcome.kind === "questions") kiosk.processingDone();
      else if (outcome.kind === "no_questions") kiosk.skipQuestions();
      else setError(outcome.detail);
    })().catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const stepTimer = setInterval(() => setActiveIndex((i) => Math.min(i + 1, 5)), STEP_DURATION);
    const statusTimer = setInterval(() => setStatusIndex((i) => (i + 1) % statusTexts.length), 900);
    return () => {
      clearInterval(stepTimer);
      clearInterval(statusTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const steps: Step[] = [
    { label: t("stepReportReceived"), status: "done" },
    { label: t("stepReportUploaded"), status: "done" },
    { label: t("stepReading"), status: activeIndex > 2 ? "done" : "active" },
    { label: t("stepPreparingSummary"), status: activeIndex > 3 ? "done" : activeIndex === 3 ? "active" : "pending" },
    { label: t("stepPreparingDoctorSummary"), status: activeIndex > 4 ? "done" : activeIndex === 4 ? "active" : "pending" },
  ];

  if (error) {
    return (
      <KioskLayout
        avatarSlot={
          <div className="flex flex-col items-center gap-2 pt-2">
            <Avatar state="idle" size={100} />
            <AvatarSpeechBubble text={t("notReportAvatar")} />
          </div>
        }
      >
        <div className="flex flex-1 flex-col items-center justify-center gap-5 py-2 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-danger/10">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
              <path d="M12 9v4m0 4h.01M10.29 3.86l-8.18 14.18A1.5 1.5 0 0 0 3.5 20h17a1.5 1.5 0 0 0 1.39-1.96L13.71 3.86a1.5 1.5 0 0 0-2.42 0Z"
                stroke="#D64545" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <h1 className="max-w-xs text-lg font-extrabold leading-tight text-primary-dark">{t("notReportTitle")}</h1>
          <p className="max-w-xs text-sm leading-relaxed text-text-secondary">{error}</p>
          <PrimaryButton onClick={kiosk.reset}>{t("tryAnotherReport")}</PrimaryButton>
        </div>
      </KioskLayout>
    );
  }

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state="processing" size={100} />
          <AvatarSpeechBubble text={t("avatarProcessing")} />
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-6 py-2 text-center">
        <h1 className="max-w-xs text-lg font-extrabold leading-tight text-primary-dark">{t("processingTitle")}</h1>

        <ProcessingAnimation />

        <AnimatePresence mode="wait">
          <motion.p
            key={statusIndex}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.3 }}
            className="text-xs font-semibold text-primary-green"
          >
            {statusTexts[statusIndex]}
          </motion.p>
        </AnimatePresence>

        <div className="w-full max-w-xs rounded-2xl bg-white p-4 text-left shadow-sm">
          <ProgressSteps steps={steps} />
        </div>
      </div>
    </KioskLayout>
  );
}
