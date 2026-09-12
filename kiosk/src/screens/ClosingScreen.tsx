import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { SuccessCheck } from "../components/SuccessState";
import { AutoResetTimer } from "../components/AutoResetTimer";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

export function ClosingScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state="closing" size={120} />
          <AvatarSpeechBubble text={t("avatarClosingNo")} />
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-2 text-center">
        <SuccessCheck size={84} />
        <h1 className="max-w-xs text-xl font-extrabold leading-tight text-primary-dark">{t("closingNoTitle")}</h1>
      </div>

      <div className="pt-4">
        <AutoResetTimer seconds={10} onComplete={kiosk.reset} />
      </div>
    </KioskLayout>
  );
}
