import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useLanguage } from "../i18n/LanguageContext";

export function AutoResetTimer({ seconds, onComplete }: { seconds: number; onComplete: () => void }) {
  const { t } = useLanguage();
  const [remaining, setRemaining] = useState(seconds);

  useEffect(() => {
    setRemaining(seconds);
    const interval = setInterval(() => {
      setRemaining((r) => Math.max(0, r - 1));
    }, 1000);
    const timeout = setTimeout(onComplete, seconds * 1000);
    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seconds]);

  return (
    <div className="mx-auto w-full max-w-[220px]">
      <p className="mb-2 text-center text-xs font-medium text-text-secondary">
        {t("autoResetNote", { n: remaining })}
      </p>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-mint-2">
        <motion.div
          className="h-full rounded-full bg-primary-green"
          initial={{ width: "100%" }}
          animate={{ width: "0%" }}
          transition={{ duration: seconds, ease: "linear" }}
        />
      </div>
    </div>
  );
}
