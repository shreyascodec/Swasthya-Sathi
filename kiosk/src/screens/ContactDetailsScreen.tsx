import { useState } from "react";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { PrimaryButton } from "../components/PrimaryButton";
import { PhoneInput } from "../components/PhoneInput";
import { EmailInput } from "../components/EmailInput";
import { ContactPreferenceOption, WhatsAppIcon, EmailIcon } from "../components/ContactPreference";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function ContactDetailsScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();
  const { contact } = kiosk.data;
  const [touched, setTouched] = useState(false);

  const noneSelected = !contact.useWhatsapp && !contact.useEmail;
  const phoneInvalid = contact.useWhatsapp && contact.phone.length !== 10;
  const emailInvalid = contact.useEmail && !EMAIL_RE.test(contact.email);
  const canSubmit = !noneSelected && !phoneInvalid && !emailInvalid;

  function handleSubmit() {
    setTouched(true);
    if (canSubmit) kiosk.submitContact();
  }

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex justify-center pt-2">
          <Avatar state="idle" size={84} />
        </div>
      }
    >
      <h1 className="pt-1 text-center text-xl font-extrabold leading-tight text-primary-dark">
        {t("contactTitle")}
      </h1>

      <div className="mt-5 flex-1 space-y-4">
        <div className="space-y-2.5">
          <ContactPreferenceOption
            icon={<WhatsAppIcon />}
            label={t("whatsappLabel")}
            checked={contact.useWhatsapp}
            onToggle={() => kiosk.updateContact({ useWhatsapp: !contact.useWhatsapp })}
          />
          <ContactPreferenceOption
            icon={<EmailIcon />}
            label={t("emailLabel")}
            checked={contact.useEmail}
            onToggle={() => kiosk.updateContact({ useEmail: !contact.useEmail })}
          />
        </div>

        {contact.useWhatsapp && (
          <PhoneInput
            value={contact.phone}
            onChange={(phone) => kiosk.updateContact({ phone })}
            error={touched && phoneInvalid ? t("phoneError") : undefined}
          />
        )}

        {contact.useEmail && (
          <EmailInput
            value={contact.email}
            onChange={(email) => kiosk.updateContact({ email })}
            error={touched && emailInvalid ? t("emailError") : undefined}
          />
        )}

        {touched && noneSelected && (
          <p className="text-center text-xs font-medium text-danger">{t("selectAtLeastOne")}</p>
        )}
      </div>

      <div className="pt-4">
        <PrimaryButton onClick={handleSubmit}>{t("sendSummary")}</PrimaryButton>
      </div>
    </KioskLayout>
  );
}
