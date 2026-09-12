import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { PrimaryButton } from "../components/PrimaryButton";
import { SuccessCheck } from "../components/SuccessState";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

type Status = "entering" | "verifying" | "success";

export function IdVerifyScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();
  const idType = kiosk.data.idType ?? "abha";
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [status, setStatus] = useState<Status>("entering");
  const [touched, setTouched] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  const otp = digits.join("");
  const isComplete = otp.length === 6;

  useEffect(() => {
    if (status !== "success") return;
    const timer = setTimeout(() => kiosk.idVerified(), 1300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  function handleDigitChange(index: number, raw: string) {
    const digit = raw.replace(/\D/g, "").slice(-1);
    setDigits((prev) => {
      const next = [...prev];
      next[index] = digit;
      return next;
    });
    if (digit && index < 5) inputRefs.current[index + 1]?.focus();
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  }

  function handleVerify() {
    setTouched(true);
    if (!isComplete || status !== "entering") return;
    setStatus("verifying");
    setTimeout(() => setStatus("success"), 1300);
  }

  function handleResend() {
    setDigits(Array(6).fill(""));
    setTouched(false);
    setStatus("entering");
    inputRefs.current[0]?.focus();
  }

  return (
    <KioskLayout avatarSlot={<div className="flex justify-center pt-2"><Avatar state={status === "success" ? "success" : "idle"} size={84} /></div>}>
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-2 text-center">
        <AnimatePresence mode="wait">
          {status === "success" ? (
            <motion.div
              key="success"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col items-center gap-3"
            >
              <SuccessCheck size={72} />
              <h1 className="text-lg font-extrabold text-primary-dark">{t("verifiedSuccessTitle")}</h1>
              <p className="max-w-xs text-xs text-text-secondary">
                {t(idType === "abha" ? "verifiedSuccessAbha" : "verifiedSuccessAadhaar")}
              </p>
            </motion.div>
          ) : (
            <motion.div key="entry" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="w-full">
              <h1 className="text-lg font-extrabold leading-tight text-primary-dark">{t("verifyTitle")}</h1>
              <p className="mx-auto mt-1.5 max-w-xs text-xs leading-relaxed text-text-secondary">
                {t("otpSentTo")} {t("otpMasked")}
              </p>

              <div className="mt-5 flex justify-center gap-2">
                {digits.map((digit, i) => (
                  <input
                    key={i}
                    ref={(el) => {
                      inputRefs.current[i] = el;
                    }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={digit}
                    disabled={status === "verifying"}
                    onChange={(e) => handleDigitChange(i, e.target.value)}
                    onKeyDown={(e) => handleKeyDown(i, e)}
                    className={`h-12 w-10 rounded-xl border-2 bg-white text-center text-lg font-bold text-text-primary outline-none ${
                      touched && !isComplete ? "border-danger" : "border-primary-dark/10 focus:border-primary-green"
                    }`}
                  />
                ))}
              </div>
              {touched && !isComplete && <p className="mt-2 text-xs font-medium text-danger">{t("otpError")}</p>}

              <button
                type="button"
                onClick={handleResend}
                disabled={status === "verifying"}
                className="mt-4 text-xs font-semibold text-primary-dark underline decoration-dotted underline-offset-4"
              >
                {t("resendOtp")}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {status !== "success" && (
        <div className="flex flex-col gap-3 pt-4">
          <PrimaryButton onClick={handleVerify} disabled={status === "verifying"}>
            {status === "verifying" ? t("verifying") : t("verifyBtn")}
          </PrimaryButton>
          <button
            type="button"
            onClick={kiosk.skipId}
            className="text-xs font-semibold text-text-secondary underline decoration-dotted underline-offset-4"
          >
            {t("skipForNow")}
          </button>
        </div>
      )}
    </KioskLayout>
  );
}
