import { useLanguage } from "../i18n/LanguageContext";

export function PhoneInput({
  value,
  onChange,
  error,
}: {
  value: string;
  onChange: (v: string) => void;
  error?: string;
}) {
  const { t } = useLanguage();
  return (
    <div>
      <label className="mb-1.5 block text-sm font-semibold text-text-primary">{t("phoneInputLabel")}</label>
      <div
        className={`flex items-center gap-2 rounded-2xl border-2 bg-white px-4 py-3.5 ${
          error ? "border-danger" : "border-primary-dark/10 focus-within:border-primary-green"
        }`}
      >
        <span className="text-base font-semibold text-text-secondary">+91</span>
        <div className="h-5 w-px bg-primary-dark/10" />
        <input
          type="tel"
          inputMode="numeric"
          maxLength={10}
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 10))}
          placeholder={t("phonePlaceholder")}
          className="w-full bg-transparent text-lg font-semibold text-text-primary outline-none placeholder:text-text-secondary/50"
        />
      </div>
      {error && <p className="mt-1.5 text-xs font-medium text-danger">{error}</p>}
    </div>
  );
}
