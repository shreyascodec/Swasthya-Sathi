import { motion } from "framer-motion";
import { useLanguage } from "../i18n/LanguageContext";

export function ABHAConfirmation() {
  const { t } = useLanguage();
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15, duration: 0.4 }}
      className="flex items-center gap-3 rounded-2xl border-2 border-primary-green/30 bg-mint p-4"
    >
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 300, damping: 15, delay: 0.3 }}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-success"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path d="M5 13l4 4L19 7" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </motion.div>
      <div className="min-w-0">
        <p className="text-sm font-bold text-text-primary">{t("abhaConfirmTitle")}</p>
        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="rounded-md bg-primary-dark px-1.5 py-0.5 text-[10px] font-extrabold tracking-wide text-white">
            {t("abhaConfirmSub")}
          </span>
          <span className="truncate text-xs text-text-secondary">{t("abhaConfirmDesc")}</span>
        </div>
      </div>
    </motion.div>
  );
}
