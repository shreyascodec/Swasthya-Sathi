import { useRef, useState } from "react";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { QRCodeCard } from "../components/QRCodeCard";
import { DotLoader } from "../components/ProcessingAnimation";
import { PrimaryButton } from "../components/PrimaryButton";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";
import { usePipeline } from "../state/PipelineContext";

export function QrUploadScreen() {
  const { t, lang } = useLanguage();
  const kiosk = useKiosk();
  const { uploadReport } = usePipeline();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function onFilePicked(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      await uploadReport([file], lang);
      kiosk.completeMobileUpload(); // -> uploaded + PROCESSING_REPORT
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setUploading(false);
    }
  }

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state="speaking" size={84} />
          <AvatarSpeechBubble text={t("avatarQr")} />
        </div>
      }
    >
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 text-center">
        <h1 className="max-w-xs text-base font-extrabold leading-tight text-primary-dark">{t("qrTitle")}</h1>

        <input ref={fileRef} type="file" accept=".pdf,image/*" className="hidden" onChange={onFilePicked} />

        {/* Primary path for the demo: upload the report from the kiosk itself. */}
        <div className="w-full max-w-xs">
          <PrimaryButton onClick={() => !uploading && fileRef.current?.click()}>
            {uploading ? t("mobileUploading") : t("uploadDocument")}
          </PrimaryButton>
        </div>
        {error && (
          <p className="max-w-xs rounded-xl bg-danger/10 px-3 py-2 text-xs font-medium text-danger">{error}</p>
        )}

        <div className="flex w-full max-w-xs items-center gap-2 pt-1">
          <span className="h-px flex-1 bg-mint-2" />
          <span className="text-[11px] font-medium uppercase text-text-secondary">{t("orDivider")}</span>
          <span className="h-px flex-1 bg-mint-2" />
        </div>

        {/* Cross-device QR upload — visual for now (mobile flow is future work). */}
        <QRCodeCard size={118} />
        <div className="flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1.5 shadow-sm">
          <span className="text-xs font-semibold text-primary-dark">{t("qrComingSoon")}</span>
          <DotLoader />
        </div>

        <button
          type="button"
          onClick={kiosk.openMobileUpload}
          className="text-[11px] font-medium text-text-secondary/70 underline decoration-dotted underline-offset-4"
        >
          {t("simulateMobileUpload")}
        </button>
      </div>
    </KioskLayout>
  );
}
