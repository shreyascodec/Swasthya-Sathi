import { motion } from "framer-motion";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

export function IdentifyScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state="speaking" size={100} />
          <AvatarSpeechBubble text={t("avatarIdentify")} />
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-2 text-center">
        <div>
          <h1 className="text-lg font-extrabold leading-tight text-primary-dark">{t("identifyTitle")}</h1>
          <p className="mx-auto mt-1.5 max-w-xs text-xs leading-relaxed text-text-secondary">
            {t("identifyDesc")}
          </p>
        </div>

        <div className="flex w-full max-w-xs flex-col gap-3">
          <IdOption
            icon={<AbhaIcon />}
            title={t("optionAbha")}
            desc={t("optionAbhaDesc")}
            onClick={() => kiosk.chooseIdType("abha")}
          />
          <IdOption
            icon={<AadhaarIcon />}
            title={t("optionAadhaar")}
            desc={t("optionAadhaarDesc")}
            onClick={() => kiosk.chooseIdType("aadhaar")}
          />
        </div>

        <button
          type="button"
          onClick={kiosk.skipId}
          className="mt-1 text-xs font-semibold text-text-secondary underline decoration-dotted underline-offset-4"
        >
          {t("optionSkipId")}
        </button>
      </div>
    </KioskLayout>
  );
}

function IdOption({
  icon,
  title,
  desc,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
  onClick: () => void;
}) {
  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.97 }}
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-2xl border-2 border-primary-dark/10 bg-white px-4 py-3.5 text-left shadow-sm active:border-primary-green"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-mint">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold text-text-primary">{title}</p>
        <p className="truncate text-[11px] text-text-secondary">{desc}</p>
      </div>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="shrink-0">
        <path d="M9 6l6 6-6 6" stroke="#66817D" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </motion.button>
  );
}

function AbhaIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <rect x="2" y="5" width="20" height="14" rx="2.5" fill="#0F5C55" />
      <circle cx="8" cy="12" r="2.5" fill="white" />
      <path d="M13 10h6M13 14h4" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function AadhaarIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" fill="#36B878" />
      <path
        d="M12 6a3.2 3.2 0 1 1 0 6.4A3.2 3.2 0 0 1 12 6Zm0 7.2c2.9 0 5.4 1.6 5.4 3.6v.4a8.6 8.6 0 0 1-10.8 0v-.4c0-2 2.5-3.6 5.4-3.6Z"
        fill="white"
      />
    </svg>
  );
}
