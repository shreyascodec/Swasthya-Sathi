import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { PrimaryButton } from "../components/PrimaryButton";
import { SecondaryButton } from "../components/SecondaryButton";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

export function ShareChoiceScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-3 pt-2">
          <Avatar state="speaking" size={140} />
          <AvatarSpeechBubble text={t("avatarShareChoice")} />
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
        <div className="flex w-full max-w-xs flex-col gap-3">
          <PrimaryButton onClick={() => kiosk.chooseShare("yes")}>{t("shareYes")}</PrimaryButton>
          <SecondaryButton onClick={() => kiosk.chooseShare("no")}>{t("shareNo")}</SecondaryButton>
        </div>
      </div>
    </KioskLayout>
  );
}
