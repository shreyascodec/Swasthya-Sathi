import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { MedicalSummary } from "../components/MedicalSummary";
import { PrimaryButton } from "../components/PrimaryButton";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

export function SummaryScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state="speaking" size={84} />
          <AvatarSpeechBubble text={t("avatarSummary")} />
        </div>
      }
    >
      <h1 className="pt-1 text-center text-xl font-extrabold text-primary-dark">{t("summaryTitle")}</h1>

      <div className="mt-4 flex-1 space-y-4">
        <MedicalSummary />
      </div>

      <div className="pt-4">
        <PrimaryButton onClick={kiosk.continueFromSummary}>{t("continueBtn")}</PrimaryButton>
      </div>
    </KioskLayout>
  );
}
