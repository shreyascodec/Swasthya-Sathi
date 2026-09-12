import { AnimatePresence } from "framer-motion";
import { LanguageProvider } from "./i18n/LanguageContext";
import { PipelineProvider } from "./state/PipelineContext";
import { KioskContext, useKioskFlowState, useKiosk } from "./state/useKioskFlow";
import { KioskFrame } from "./components/KioskFrame";
import { MobileUploadOverlay } from "./mobile/MobileUploadOverlay";

import { WelcomeScreen } from "./screens/WelcomeScreen";
import { IdentifyScreen } from "./screens/IdentifyScreen";
import { IdEntryScreen } from "./screens/IdEntryScreen";
import { IdVerifyScreen } from "./screens/IdVerifyScreen";
import { QrUploadScreen } from "./screens/QrUploadScreen";
import { ProcessingScreen } from "./screens/ProcessingScreen";
import { QuestionScreen } from "./screens/QuestionScreen";
import { GeneratingSummaryScreen } from "./screens/GeneratingSummaryScreen";
import { SummaryScreen } from "./screens/SummaryScreen";
import { ShareChoiceScreen } from "./screens/ShareChoiceScreen";
import { ContactDetailsScreen } from "./screens/ContactDetailsScreen";
import { ShareSuccessScreen } from "./screens/ShareSuccessScreen";
import { ClosingScreen } from "./screens/ClosingScreen";

function KioskApp() {
  const kiosk = useKiosk();

  return (
    <KioskFrame>
      <div className="relative h-full w-full">
        <AnimatePresence mode="wait">
          {kiosk.screen === "WELCOME" && <WelcomeScreen key="welcome" />}
          {kiosk.screen === "IDENTIFY" && <IdentifyScreen key="identify" />}
          {kiosk.screen === "ID_ENTRY" && <IdEntryScreen key="id-entry" />}
          {kiosk.screen === "ID_VERIFY" && <IdVerifyScreen key="id-verify" />}
          {kiosk.screen === "QR_UPLOAD" && <QrUploadScreen key="qr" />}
          {kiosk.screen === "PROCESSING_REPORT" && <ProcessingScreen key="processing" />}
          {kiosk.screen === "QUESTIONS" && <QuestionScreen key="questions" />}
          {kiosk.screen === "GENERATING_SUMMARY" && <GeneratingSummaryScreen key="generating" />}
          {kiosk.screen === "SUMMARY" && <SummaryScreen key="summary" />}
          {kiosk.screen === "SHARE_CHOICE" && <ShareChoiceScreen key="share-choice" />}
          {kiosk.screen === "CONTACT_DETAILS" && <ContactDetailsScreen key="contact" />}
          {kiosk.screen === "SHARE_SUCCESS" && <ShareSuccessScreen key="share-success" />}
          {kiosk.screen === "CLOSING" && <ClosingScreen key="closing" />}
        </AnimatePresence>

        <MobileUploadOverlay />
      </div>
    </KioskFrame>
  );
}

function KioskProvider({ children }: { children: React.ReactNode }) {
  const value = useKioskFlowState();
  return <KioskContext.Provider value={value}>{children}</KioskContext.Provider>;
}

export default function App() {
  return (
    <LanguageProvider>
      <PipelineProvider>
        <KioskProvider>
          <KioskApp />
        </KioskProvider>
      </PipelineProvider>
    </LanguageProvider>
  );
}
