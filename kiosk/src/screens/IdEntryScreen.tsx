import { useState } from "react";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { PrimaryButton } from "../components/PrimaryButton";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

const ID_LENGTH: Record<"abha" | "aadhaar", number> = {
  abha: 14,
  aadhaar: 12,
};

export function IdEntryScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();
  const idType = kiosk.data.idType ?? "abha";
  const [value, setValue] = useState("");
  const [touched, setTouched] = useState(false);

  const requiredLength = ID_LENGTH[idType];
  const isValid = value.length === requiredLength;

  function handleSubmit() {
    setTouched(true);
    if (isValid) kiosk.submitIdNumber(value);
  }

  return (
    <KioskLayout avatarSlot={<div className="flex justify-center pt-2"><Avatar state="idle" size={84} /></div>}>
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-2 text-center">
        <div>
          <h1 className="text-lg font-extrabold leading-tight text-primary-dark">
            {t(idType === "abha" ? "abhaEntryTitle" : "aadhaarEntryTitle")}
          </h1>
          <p className="mx-auto mt-1.5 max-w-xs text-xs leading-relaxed text-text-secondary">
            {t("idEntryDesc")}
          </p>
        </div>

        <div className="w-full max-w-xs text-left">
          <label className="mb-1.5 block text-sm font-semibold text-text-primary">
            {t(idType === "abha" ? "abhaNumberLabel" : "aadhaarNumberLabel")}
          </label>
          <div
            className={`flex items-center rounded-2xl border-2 bg-white px-4 py-3.5 ${
              touched && !isValid ? "border-danger" : "border-primary-dark/10 focus-within:border-primary-green"
            }`}
          >
            <input
              type="text"
              inputMode="numeric"
              value={value}
              onChange={(e) => setValue(e.target.value.replace(/\D/g, "").slice(0, requiredLength))}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              placeholder={t(idType === "abha" ? "abhaPlaceholder" : "aadhaarPlaceholder")}
              className="w-full bg-transparent text-lg font-semibold tracking-wide text-text-primary outline-none placeholder:text-text-secondary/50"
            />
          </div>
          {touched && !isValid && <p className="mt-1.5 text-xs font-medium text-danger">{t("idNumberError")}</p>}
        </div>
      </div>

      <div className="flex flex-col gap-3 pt-4">
        <PrimaryButton onClick={handleSubmit}>{t("sendOtpBtn")}</PrimaryButton>
        <button
          type="button"
          onClick={kiosk.skipId}
          className="text-xs font-semibold text-text-secondary underline decoration-dotted underline-offset-4"
        >
          {t("skipForNow")}
        </button>
      </div>
    </KioskLayout>
  );
}
