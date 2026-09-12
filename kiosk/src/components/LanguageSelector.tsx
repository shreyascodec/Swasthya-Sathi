import { useLanguage } from "../i18n/LanguageContext";

export function LanguageSelector() {
  const { lang, setLang, t } = useLanguage();

  return (
    <div className="flex shrink-0 items-center rounded-full bg-mint p-1 text-[11px] font-semibold">
      <button
        type="button"
        onClick={() => setLang("hi")}
        className={`whitespace-nowrap rounded-full px-2.5 py-1.5 transition-colors ${
          lang === "hi" ? "bg-primary-dark text-white shadow-sm" : "text-primary-dark/70"
        }`}
      >
        {t("langHi")}
      </button>
      <button
        type="button"
        onClick={() => setLang("en")}
        className={`whitespace-nowrap rounded-full px-2.5 py-1.5 transition-colors ${
          lang === "en" ? "bg-primary-dark text-white shadow-sm" : "text-primary-dark/70"
        }`}
      >
        {t("langEn")}
      </button>
    </div>
  );
}
