import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { SuccessCheck } from "../components/SuccessState";
import { AutoResetTimer } from "../components/AutoResetTimer";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

export function ShareSuccessScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state="closing" size={92} />
          <AvatarSpeechBubble text={t("avatarShareSuccessClosing")} />
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-2 text-center">
        <SuccessCheck size={84} />
        <h1 className="max-w-xs text-xl font-extrabold leading-tight text-primary-dark">{t("shareSuccessTitle")}</h1>

        <div className="w-full max-w-xs space-y-2">
          <ChecklistRow label={t("successDoctorLine")} />
          <ChecklistRow label={t("successPatientLine")} />
        </div>
      </div>

      <div className="pt-4">
        <AutoResetTimer seconds={10} onComplete={kiosk.reset} />
      </div>
    </KioskLayout>
  );
}

function ChecklistRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2.5 rounded-xl bg-white px-4 py-2.5 shadow-sm">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
          <path d="M5 13l4 4L19 7" stroke="white" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="text-sm font-semibold text-text-primary">{label}</span>
    </div>
  );
}
