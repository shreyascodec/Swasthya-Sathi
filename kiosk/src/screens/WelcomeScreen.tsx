import { motion } from "framer-motion";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { PrimaryButton } from "../components/PrimaryButton";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

export function WelcomeScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-4 pt-2">
          <Avatar state="greeting" variant="photo" size={172} />
          <AvatarSpeechBubble text={t("avatarGreeting")} voiceOver={false} />
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
        <div>
          <h1 className="text-[26px] font-extrabold leading-tight text-primary-dark">{t("welcomeTitle")}</h1>
          <p className="mx-auto mt-3 max-w-xs text-sm leading-relaxed text-text-secondary">{t("welcomeDesc")}</p>
        </div>

        <div className="flex items-center gap-2">
          <Tag icon={<ShieldIcon />} label={t("tagSecure")} />
          <Tag icon={<SparkIcon />} label={t("tagAiAssisted")} />
          <Tag icon={<HeartIcon />} label={t("tagSimple")} />
        </div>
      </div>

      <div className="pt-2 pb-6">
        <PrimaryButton onClick={kiosk.start}>{t("getStarted")}</PrimaryButton>
      </div>
    </KioskLayout>
  );
}

function Tag({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 shadow-sm"
    >
      {icon}
      <span className="text-[11px] font-semibold text-primary-dark">{label}</span>
    </motion.div>
  );
}

function ShieldIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path d="M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6l7-3Z" fill="#36B878" />
    </svg>
  );
}
function SparkIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" fill="#0F5C55" />
    </svg>
  );
}
function HeartIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 20s-7-4.4-9.5-8.8C1 8 2.7 4.5 6.2 4c2-.3 3.7.7 5.8 3 2.1-2.3 3.8-3.3 5.8-3 3.5.5 5.2 4 3.7 7.2C19 15.6 12 20 12 20Z"
        fill="#8BCF9B"
      />
    </svg>
  );
}
