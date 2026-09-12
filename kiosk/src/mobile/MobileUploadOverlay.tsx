import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useKiosk } from "../state/useKioskFlow";
import { useLanguage } from "../i18n/LanguageContext";
import { usePipeline } from "../state/PipelineContext";
import { Logo } from "../components/Logo";
import { LanguageSelector } from "../components/LanguageSelector";
import { PrimaryButton } from "../components/PrimaryButton";
import { SuccessCheck } from "../components/SuccessState";

type Phase = "idle" | "uploading" | "success";

export function MobileUploadOverlay() {
  const kiosk = useKiosk();
  const { t, lang } = useLanguage();
  const { uploadReport } = usePipeline();
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!kiosk.data.mobileUploadOpen) {
      setPhase("idle");
      setProgress(0);
      setError(null);
    }
  }, [kiosk.data.mobileUploadOpen]);

  // Tapping the upload card opens a real file picker (report photo or PDF).
  function startUpload() {
    setError(null);
    fileRef.current?.click();
  }

  async function onFilePicked(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    setPhase("uploading");
    setProgress(15);
    const creep = setInterval(() => setProgress((p) => Math.min(p + 12, 90)), 400);
    try {
      await uploadReport([file], lang);
      clearInterval(creep);
      setProgress(100);
      setTimeout(() => setPhase("success"), 350);
    } catch (err) {
      clearInterval(creep);
      setError(err instanceof Error ? err.message : String(err));
      setPhase("idle");
      setProgress(0);
    }
  }

  return (
    <AnimatePresence>
      {kiosk.data.mobileUploadOpen && (
        <motion.div
          initial={{ y: "100%" }}
          animate={{ y: 0 }}
          exit={{ y: "100%" }}
          transition={{ type: "spring", stiffness: 260, damping: 30 }}
          className="absolute inset-0 z-40 flex flex-col bg-bg"
        >
          {/* fake phone status bar */}
          <div className="flex items-center justify-between px-6 pb-1 pt-3 text-[11px] font-semibold text-text-primary">
            <span>9:41</span>
            <div className="flex items-center gap-1">
              <svg width="14" height="10" viewBox="0 0 16 12" fill="none">
                <rect x="0" y="7" width="3" height="5" rx="0.5" fill="currentColor" />
                <rect x="4.5" y="5" width="3" height="7" rx="0.5" fill="currentColor" />
                <rect x="9" y="3" width="3" height="9" rx="0.5" fill="currentColor" />
                <rect x="13.5" y="0" width="3" height="12" rx="0.5" fill="currentColor" />
              </svg>
              <svg width="18" height="10" viewBox="0 0 22 12" fill="none">
                <rect x="0.5" y="0.5" width="18" height="11" rx="2.5" stroke="currentColor" />
                <rect x="2" y="2" width="15" height="8" rx="1.2" fill="currentColor" />
                <rect x="20" y="4" width="1.5" height="4" rx="0.5" fill="currentColor" />
              </svg>
            </div>
          </div>

          <div className="flex items-center justify-between px-5 py-2">
            <Logo compact />
            <LanguageSelector />
          </div>

          <div className="flex flex-1 flex-col justify-center px-6">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,image/*"
              className="hidden"
              onChange={onFilePicked}
            />
            <AnimatePresence mode="wait">
              {phase !== "success" && (
                <motion.div
                  key="upload"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="text-center"
                >
                  <h1 className="text-2xl font-extrabold text-text-primary">{t("mobileTitle")}</h1>
                  <p className="mx-auto mt-2 max-w-xs text-sm text-text-secondary">{t("mobileDesc")}</p>

                  <motion.button
                    type="button"
                    whileTap={{ scale: phase === "idle" ? 0.97 : 1 }}
                    onClick={phase === "idle" ? startUpload : undefined}
                    className="mt-8 flex w-full flex-col items-center gap-3 rounded-3xl border-2 border-dashed border-primary-green/50 bg-white px-6 py-10 shadow-sm"
                  >
                    {phase === "idle" ? (
                      <>
                        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-mint">
                          <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                            <path
                              d="M12 16V4m0 0-4 4m4-4 4 4M5 16v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2"
                              stroke="#0F5C55"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </div>
                        <p className="text-base font-bold text-primary-dark">{t("mobileUploadCard")}</p>
                        <p className="text-xs text-text-secondary">{t("mobileFormats")}</p>
                      </>
                    ) : (
                      <div className="w-full">
                        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-mint">
                          <motion.svg
                            width="26"
                            height="26"
                            viewBox="0 0 24 24"
                            fill="none"
                            animate={{ rotate: 360 }}
                            transition={{ duration: 1.2, repeat: Infinity, ease: "linear" }}
                          >
                            <path
                              d="M12 3a9 9 0 1 0 9 9"
                              stroke="#36B878"
                              strokeWidth="2.4"
                              strokeLinecap="round"
                            />
                          </motion.svg>
                        </div>
                        <p className="mb-2 text-sm font-semibold text-text-primary">{t("mobileUploading")}</p>
                        <div className="h-2.5 w-full overflow-hidden rounded-full bg-mint-2">
                          <motion.div
                            className="h-full rounded-full bg-gradient-to-r from-primary-green to-primary-green-2"
                            animate={{ width: `${progress}%` }}
                            transition={{ duration: 0.4, ease: "easeOut" }}
                          />
                        </div>
                        <p className="mt-1.5 text-right text-xs font-bold text-primary-dark">{progress}%</p>
                      </div>
                    )}
                  </motion.button>

                  {error && (
                    <p className="mt-4 rounded-xl bg-danger/10 px-4 py-2 text-xs font-medium text-danger">
                      {error}
                    </p>
                  )}
                </motion.div>
              )}

              {phase === "success" && (
                <motion.div
                  key="success"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.4 }}
                  className="text-center"
                >
                  <SuccessCheck size={96} />
                  <h1 className="mt-6 text-2xl font-extrabold text-text-primary">{t("mobileSuccessTitle")}</h1>
                  <p className="mx-auto mt-2 max-w-xs text-sm text-text-secondary">{t("mobileSuccessSub")}</p>
                  <div className="mt-8">
                    <PrimaryButton onClick={kiosk.completeMobileUpload}>{t("mobileDone")}</PrimaryButton>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
