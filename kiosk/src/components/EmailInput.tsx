import { useLanguage } from "../i18n/LanguageContext";

export function EmailInput({
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
      <label className="mb-1.5 block text-sm font-semibold text-text-primary">{t("emailInputLabel")}</label>
      <div
        className={`flex items-center gap-2 rounded-2xl border-2 bg-white px-4 py-3.5 ${
          error ? "border-danger" : "border-primary-dark/10 focus-within:border-primary-green"
        }`}
      >
        <input
          type="email"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t("emailPlaceholder")}
          className="w-full bg-transparent text-lg font-semibold text-text-primary outline-none placeholder:text-text-secondary/50"
        />
      </div>
      {error && <p className="mt-1.5 text-xs font-medium text-danger">{error}</p>}
    </div>
  );
}
