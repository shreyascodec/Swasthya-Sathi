import type { Lang } from "../types";

export const translations = {
  hi: {
    brand: "स्वास्थ्य सखी",
    brandSub: "डिजिटल स्वास्थ्य सहायक",
    langHi: "हिन्दी",
    langEn: "English",

    // Welcome
    welcomeTitle: "स्वास्थ्य सखी में आपका स्वागत है",
    welcomeDesc:
      "अपना ANC कार्ड या रिपोर्ट अपलोड करें और अपनी भाषा में मातृ स्वास्थ्य जोखिम जांच पाएं।",
    getStarted: "शुरू करें",
    avatarGreeting:
      "नमस्ते! मैं स्वास्थ्य सखी हूं। सुरक्षित गर्भावस्था के लिए मैं आपकी रिपोर्ट और कुछ खतरे के लक्षण जांचूंगी।",
    tagSecure: "सुरक्षित",
    tagSimple: "सरल",
    tagAiAssisted: "AI-सहायता प्राप्त",

    // Identify
    identifyTitle: "अपनी पहचान बताएं",
    identifyDesc: "आप ABHA ID या आधार ID से आगे बढ़ सकते हैं, या इनके बिना भी जारी रख सकते हैं।",
    avatarIdentify:
      "क्या आप अपनी ABHA ID या आधार ID से आगे बढ़ना चाहेंगे? आप चाहें तो इनके बिना भी जारी रख सकते हैं।",
    optionAbha: "ABHA ID से आगे बढ़ें",
    optionAbhaDesc: "आयुष्मान भारत हेल्थ अकाउंट",
    optionAadhaar: "आधार ID से आगे बढ़ें",
    optionAadhaarDesc: "आधार नंबर से सत्यापन",
    optionSkipId: "इनके बिना आगे बढ़ें",

    abhaEntryTitle: "अपनी ABHA ID दर्ज करें",
    aadhaarEntryTitle: "अपनी आधार ID दर्ज करें",
    abhaNumberLabel: "ABHA ID",
    aadhaarNumberLabel: "आधार नंबर",
    abhaPlaceholder: "14-1234-5678-9012",
    aadhaarPlaceholder: "1234 5678 9012",
    idEntryDesc: "यह जानकारी आपके डॉक्टर के साथ सुरक्षित रूप से जोड़ने के लिए उपयोग होगी।",
    idNumberError: "कृपया सही नंबर दर्ज करें",
    sendOtpBtn: "OTP भेजें",

    verifyTitle: "OTP सत्यापन",
    otpSentTo: "आपके पंजीकृत मोबाइल नंबर पर 6 अंकों का OTP भेजा गया है",
    otpMasked: "•••••• 43210",
    enterOtp: "OTP दर्ज करें",
    verifyBtn: "सत्यापित करें",
    verifying: "सत्यापित किया जा रहा है...",
    resendOtp: "OTP दोबारा भेजें",
    otpError: "कृपया 6 अंकों का सही OTP दर्ज करें",
    verifiedSuccessTitle: "सत्यापन सफल!",
    verifiedSuccessAbha: "आपकी ABHA ID सफलतापूर्वक सत्यापित हो गई",
    verifiedSuccessAadhaar: "आपकी आधार ID सफलतापूर्वक सत्यापित हो गई",
    skipForNow: "अभी छोड़ें",

    // QR Upload
    qrTitle: "अपनी रिपोर्ट मोबाइल से अपलोड करें",
    qrScanInstruction: "अपने मोबाइल कैमरे से QR कोड स्कैन करें",
    qrStep1: "QR स्कैन करें",
    qrStep2: "रिपोर्ट अपलोड करें",
    qrStep3: "मोबाइल पर सफलता संदेश देखें",
    avatarQr:
      "कृपया इस QR कोड को अपने मोबाइल से स्कैन करें और अपनी मेडिकल रिपोर्ट अपलोड करें।",
    waitingUpload: "अपलोड की प्रतीक्षा है",
    uploadDocument: "दस्तावेज़ अपलोड करें",
    qrComingSoon: "मोबाइल अपलोड — जल्द आ रहा है",
    simulateMobileUpload: "(डेमो: मोबाइल स्कैन सिम्युलेट करें)",

    // Mobile
    mobileTitle: "अपनी रिपोर्ट अपलोड करें",
    mobileDesc: "अपनी मेडिकल रिपोर्ट की साफ फोटो या PDF अपलोड करें।",
    mobileUploadCard: "ANC कार्ड / रिपोर्ट अपलोड करें",
    mobileFormats: "PDF, JPG, PNG, WEBP, BMP, TIFF समर्थित",
    mobileUploading: "रिपोर्ट अपलोड हो रही है...",
    mobileSuccessTitle: "रिपोर्ट सफलतापूर्वक अपलोड हो गई",
    mobileSuccessSub:
      "अब आप इस स्क्रीन को बंद कर सकते हैं और कियोस्क पर वापस जा सकते हैं।",
    mobileDone: "Done",
    mobileClosedTitle: "आप अब कियोस्क पर वापस जा सकते हैं",

    // Processing
    processingTitle: "आपकी रिपोर्ट तैयार की जा रही है",
    avatarProcessing:
      "धन्यवाद! आपकी रिपोर्ट प्राप्त हो गई है। अब मैं रिपोर्ट को समझने योग्य सारांश में तैयार कर रही हूं।",
    stepReportReceived: "रिपोर्ट प्राप्त हुई",
    stepReportUploaded: "रिपोर्ट सुरक्षित रूप से अपलोड हुई",
    stepReading: "रिपोर्ट पढ़ी जा रही है",
    stepPreparingSummary: "सारांश तैयार किया जा रहा है",
    stepPreparingDoctorSummary: "डॉक्टर के लिए सारांश तैयार किया जा रहा है",
    statusReading: "रिपोर्ट पढ़ी जा रही है...",
    statusExtracting: "महत्वपूर्ण जानकारी निकाली जा रही है...",
    statusOrganizing: "मेडिकल निष्कर्ष व्यवस्थित किए जा रहे हैं...",
    statusPreparing: "सारांश तैयार किया जा रहा है...",

    // Questions
    questionOf: "प्रश्न {n} / {total}",
    q1: "क्या आपको इस समय कोई परेशानी या लक्षण महसूस हो रहे हैं?",
    q2: "क्या आप वर्तमान में कोई दवा ले रहे हैं?",
    q3: "क्या आपको पहले से कोई बीमारी है?",
    q4: "क्या इस रिपोर्ट के बारे में आपको कोई विशेष चिंता है?",
    q5: "क्या आप चाहते हैं कि डॉक्टर को आपकी रिपोर्ट के साथ आपकी यह जानकारी भी भेजी जाए?",
    yes: "हाँ",
    no: "नहीं",
    listening: "सुन रही हूं...",
    askingQuestion: "पूछ रही हूं...",
    tapMicToSpeak: "बोलने के लिए माइक दबाएं",
    recordingAnswer: "सुना जा रहा है...",
    orDivider: "या",
    typePlaceholder: "यहां अपना जवाब लिखें...",
    yourAnswer: "आपका जवाब",
    transcribing: "लिखा जा रहा है...",
    tapToStop: "रोकने के लिए दबाएं",
    micBlocked: "माइक्रोफ़ोन उपलब्ध नहीं है। कृपया ब्राउज़र में अनुमति दें।",
    answerRecorded: "जवाब दर्ज हुआ",
    refShort: "रेंज",
    summaryEmpty: "इस दस्तावेज़ से कोई मेडिकल मान नहीं निकाला जा सका।",
    notReportTitle: "यह लैब रिपोर्ट नहीं लगती",
    notReportAvatar: "क्षमा करें, यह एक वैध लैब रिपोर्ट नहीं लगती। कृपया सही रिपोर्ट अपलोड करें।",
    tryAnotherReport: "दूसरी रिपोर्ट आज़माएं",
    voiceAnswer1: "हाँ, हल्का सिरदर्द है",
    voiceAnswer2: "नहीं, कोई दवा नहीं ले रहा हूं",
    voiceAnswer3: "नहीं, कोई बीमारी नहीं है",
    voiceAnswer4: "नहीं, कोई खास चिंता नहीं है",
    voiceAnswer5: "हाँ, भेज दीजिए",

    // Generating summary
    avatarGeneratingSummary:
      "बहुत धन्यवाद। अब मैं आपकी रिपोर्ट और आपके जवाबों के आधार पर डॉक्टर के लिए सारांश तैयार कर रही हूं।",
    stepResponsesReceived: "आपके जवाब प्राप्त हुए",
    stepFindingsIdentified: "महत्वपूर्ण निष्कर्ष पहचाने गए",
    stepSendingToDoctor: "डॉक्टर को भेजा जा रहा है",

    // Summary
    summaryTitle: "आपकी मातृ स्वास्थ्य जांच",
    patientOverview: "मरीज़ का विवरण",
    ageLabel: "आयु",
    ageValue: "42 वर्ष",
    keyFindings: "मुख्य निष्कर्ष",
    importantValues: "महत्वपूर्ण मान",
    patientResponses: "आपके जवाब",
    doctorAttention: "डॉक्टर का ध्यान आवश्यक",
    disclaimer:
      "यह सारांश केवल जानकारी के लिए है। अंतिम चिकित्सकीय सलाह आपके डॉक्टर द्वारा दी जाएगी।",
    avatarSummary:
      "यह आपकी मातृ स्वास्थ्य जोखिम जांच है। कृपया नीचे बताए गए अगले कदम का पालन करें।",
    abhaConfirmTitle: "सारांश डॉक्टर के साथ साझा किया गया",
    abhaConfirmSub: "ABHA",
    abhaConfirmDesc: "सुरक्षित स्वास्थ्य जानकारी साझाकरण",
    continueBtn: "आगे बढ़ें",
    findingBpTitle: "रक्तचाप थोड़ा अधिक है",
    findingBpDesc: "सामान्य से थोड़ा ऊपर, नियमित जांच की सलाह दी जाती है",
    findingHbTitle: "हीमोग्लोबिन सामान्य सीमा में है",
    findingHbDesc: "कोई तुरंत चिंता की बात नहीं",
    findingSugarTitle: "ब्लड शुगर पर ध्यान देने की आवश्यकता है",
    findingSugarDesc: "डॉक्टर से चर्चा करने की सलाह दी जाती है",
    normalTag: "सामान्य",
    attentionTag: "ध्यान दें",
    importantTag: "महत्वपूर्ण",
    // MCH maternal risk
    riskAssessment: "जोखिम आकलन",
    risk_high: "उच्च जोखिम",
    risk_moderate: "ध्यान देने योग्य",
    risk_low: "कम जोखिम",
    risk_unknown: "आकलन अधूरा",
    action_high: "तुरंत FRU/CHC रेफर करें। खतरे के लक्षण हों तो 108 पर कॉल करें।",
    action_moderate: "मेडिकल ऑफिसर को दिखाएं और जल्द फॉलो-अप ANC विज़िट रखें; चिह्नित मानों पर नज़र रखें।",
    action_low: "नियमित ANC जारी रखें। अगली निर्धारित विज़िट पर जाएं।",
    action_unknown: "जोखिम आकलन के लिए पर्याप्त मान नहीं। स्वास्थ्यकर्मी से जांच कराएं।",
    redFlags: "खतरे के संकेत",
    measuredValues: "मापे गए मान",
    dangerResponses: "आपके जवाब",
    mchDisclaimer: "यह एक जोखिम स्क्रीनिंग है, निदान नहीं। अंतिम सलाह आपके डॉक्टर देंगे।",

    // Share choice
    avatarShareChoice:
      "क्या आप इस सारांश की एक कॉपी अपने मोबाइल पर भी प्राप्त करना चाहते हैं?",
    shareYes: "हाँ",
    shareNo: "नहीं",

    // Contact details
    contactTitle: "सारांश कहां प्राप्त करना चाहेंगे?",
    whatsappLabel: "WhatsApp",
    emailLabel: "Email",
    phoneInputLabel: "मोबाइल नंबर दर्ज करें",
    emailInputLabel: "ईमेल पता दर्ज करें",
    phonePlaceholder: "98765 43210",
    emailPlaceholder: "aapka.naam@email.com",
    sendSummary: "सारांश भेजें",
    phoneError: "कृपया सही 10 अंकों का मोबाइल नंबर दर्ज करें",
    emailError: "कृपया सही ईमेल पता दर्ज करें",
    selectAtLeastOne: "कृपया कम से कम एक विकल्प चुनें",

    // Share success
    shareSuccessTitle: "सारांश सफलतापूर्वक साझा किया गया",
    successDoctorLine: "डॉक्टर — ABHA के माध्यम से",
    successPatientLine: "मरीज़ — WhatsApp / Email के माध्यम से",
    avatarShareSuccessClosing:
      "हो गया! आपका सारांश साझा कर दिया गया है। स्वास्थ्य का ध्यान रखें। धन्यवाद!",

    // Closing (no)
    avatarClosingNo:
      "ठीक है। धन्यवाद! आपकी रिपोर्ट का सारांश डॉक्टर के साथ साझा कर दिया गया है। आपका दिन शुभ हो।",
    closingNoTitle: "आपका दिन शुभ हो",

    autoResetNote: "{n} सेकंड में स्वागत स्क्रीन पर वापस जा रहे हैं",
    prototypeControls: "प्रोटोटाइप नियंत्रण",
    prototypeNote: "(केवल डेमो के लिए — असली कियोस्क में यह नहीं दिखेगा)",
  },
  en: {
    brand: "Swasthya Sakhi",
    brandSub: "Digital Health Assistant",
    langHi: "हिन्दी",
    langEn: "English",

    // Welcome
    welcomeTitle: "Welcome to Swasthya Sakhi",
    welcomeDesc:
      "Upload your ANC card or report and get a maternal health risk check, explained in your language.",
    getStarted: "Get Started",
    avatarGreeting:
      "Hello! I am Swasthya Sakhi. I'll check your antenatal report and a few danger signs for a safe pregnancy.",
    tagSecure: "Secure",
    tagSimple: "Simple",
    tagAiAssisted: "AI-assisted",

    // Identify
    identifyTitle: "Identify yourself",
    identifyDesc: "You can continue with your ABHA ID or Aadhaar ID, or continue without either.",
    avatarIdentify:
      "Would you like to continue with your ABHA ID or Aadhaar ID? You can also continue without them.",
    optionAbha: "Continue with ABHA ID",
    optionAbhaDesc: "Ayushman Bharat Health Account",
    optionAadhaar: "Continue with Aadhaar ID",
    optionAadhaarDesc: "Verify using your Aadhaar number",
    optionSkipId: "Continue without these",

    abhaEntryTitle: "Enter your ABHA ID",
    aadhaarEntryTitle: "Enter your Aadhaar ID",
    abhaNumberLabel: "ABHA ID",
    aadhaarNumberLabel: "Aadhaar Number",
    abhaPlaceholder: "14-1234-5678-9012",
    aadhaarPlaceholder: "1234 5678 9012",
    idEntryDesc: "This will be used to securely link your report with your doctor.",
    idNumberError: "Please enter a valid number",
    sendOtpBtn: "Send OTP",

    verifyTitle: "OTP Verification",
    otpSentTo: "A 6-digit OTP has been sent to your registered mobile number",
    otpMasked: "•••••• 43210",
    enterOtp: "Enter OTP",
    verifyBtn: "Verify",
    verifying: "Verifying...",
    resendOtp: "Resend OTP",
    otpError: "Please enter a valid 6-digit OTP",
    verifiedSuccessTitle: "Verification successful!",
    verifiedSuccessAbha: "Your ABHA ID has been verified successfully",
    verifiedSuccessAadhaar: "Your Aadhaar ID has been verified successfully",
    skipForNow: "Skip for now",

    // QR Upload
    qrTitle: "Upload your report using your mobile",
    qrScanInstruction: "Scan this QR code using your phone camera",
    qrStep1: "Scan the QR code",
    qrStep2: "Upload your report",
    qrStep3: "See success message on mobile",
    avatarQr:
      "Please scan this QR code with your mobile and upload your medical report.",
    waitingUpload: "Waiting for upload",
    uploadDocument: "Upload document",
    qrComingSoon: "Mobile upload — coming soon",
    simulateMobileUpload: "(Demo: Simulate mobile scan)",

    // Mobile
    mobileTitle: "Upload your medical report",
    mobileDesc: "Upload a clear photo or PDF of your medical report.",
    mobileUploadCard: "Upload ANC card / report",
    mobileFormats: "PDF, JPG, PNG, WEBP, BMP, TIFF supported",
    mobileUploading: "Uploading report...",
    mobileSuccessTitle: "Report uploaded successfully",
    mobileSuccessSub:
      "You can now close this screen and return to the kiosk.",
    mobileDone: "Done",
    mobileClosedTitle: "You can now return to the kiosk",

    // Processing
    processingTitle: "Your report is being processed",
    avatarProcessing:
      "Thank you! Your report has been received. I am now preparing an easy-to-understand summary.",
    stepReportReceived: "Report received",
    stepReportUploaded: "Report uploaded securely",
    stepReading: "Reading report",
    stepPreparingSummary: "Preparing summary",
    stepPreparingDoctorSummary: "Preparing doctor summary",
    statusReading: "Reading report...",
    statusExtracting: "Extracting important information...",
    statusOrganizing: "Organizing medical findings...",
    statusPreparing: "Preparing summary...",

    // Questions
    questionOf: "Question {n} of {total}",
    q1: "Are you currently experiencing any discomfort or symptoms?",
    q2: "Are you currently taking any medication?",
    q3: "Do you have any pre-existing medical condition?",
    q4: "Do you have any specific concern about this report?",
    q5: "Would you like this information to be sent to the doctor along with your report?",
    yes: "Yes",
    no: "No",
    listening: "Listening...",
    askingQuestion: "Asking...",
    tapMicToSpeak: "Tap the mic to speak",
    recordingAnswer: "Listening to you...",
    orDivider: "or",
    typePlaceholder: "Type your answer here...",
    yourAnswer: "Your answer",
    transcribing: "Transcribing...",
    tapToStop: "Tap to stop",
    micBlocked: "Microphone unavailable. Please allow access in the browser.",
    answerRecorded: "Answer recorded",
    refShort: "Ref",
    summaryEmpty: "No medical values could be extracted from this document.",
    notReportTitle: "This doesn't look like a lab report",
    notReportAvatar: "Sorry, this doesn't look like a valid lab report. Please upload the correct report.",
    tryAnotherReport: "Try another report",
    voiceAnswer1: "Yes, I have a mild headache",
    voiceAnswer2: "No, I'm not taking any medication",
    voiceAnswer3: "No, I don't have any condition",
    voiceAnswer4: "No specific concern",
    voiceAnswer5: "Yes, please send it",

    // Generating summary
    avatarGeneratingSummary:
      "Thank you. I am now preparing a summary of your report and answers for the doctor.",
    stepResponsesReceived: "Patient responses received",
    stepFindingsIdentified: "Important findings identified",
    stepSendingToDoctor: "Sending to doctor",

    // Summary
    summaryTitle: "Your Maternal Health Check",
    patientOverview: "Patient Overview",
    ageLabel: "Age",
    ageValue: "42 years",
    keyFindings: "Key Findings",
    importantValues: "Important Values",
    patientResponses: "Patient Responses",
    doctorAttention: "Doctor Attention",
    disclaimer:
      "This summary is for informational purposes only. Final medical advice will be given by your doctor.",
    avatarSummary:
      "Here is your maternal health risk check. Please follow the recommended next step below.",
    abhaConfirmTitle: "Summary shared with doctor",
    abhaConfirmSub: "ABHA",
    abhaConfirmDesc: "Secure health information sharing",
    continueBtn: "Continue",
    findingBpTitle: "Blood pressure appears elevated",
    findingBpDesc: "Slightly above normal, routine monitoring advised",
    findingHbTitle: "Hemoglobin is within normal range",
    findingHbDesc: "No immediate concern",
    findingSugarTitle: "Blood sugar requires attention",
    findingSugarDesc: "Discussing with your doctor is recommended",
    normalTag: "Normal",
    attentionTag: "Attention",
    importantTag: "Important",
    // MCH maternal risk
    riskAssessment: "Risk Assessment",
    risk_high: "High risk",
    risk_moderate: "Needs attention",
    risk_low: "Low risk",
    risk_unknown: "Assessment incomplete",
    action_high: "Refer urgently to an FRU/CHC. Call 108 if any danger sign is present.",
    action_moderate: "See the Medical Officer and schedule a follow-up ANC visit soon; monitor the flagged values.",
    action_low: "Continue routine ANC. Attend the next scheduled visit.",
    action_unknown: "Not enough readable values to assess risk. Re-check with the health worker.",
    redFlags: "Danger signs",
    measuredValues: "Measured values",
    dangerResponses: "Your responses",
    mchDisclaimer: "This is a risk screening, not a diagnosis. Final advice will be given by your doctor.",

    // Share choice
    avatarShareChoice:
      "Would you also like to receive a copy of this summary?",
    shareYes: "Yes",
    shareNo: "No",

    // Contact details
    contactTitle: "Where would you like to receive the summary?",
    whatsappLabel: "WhatsApp",
    emailLabel: "Email",
    phoneInputLabel: "Enter mobile number",
    emailInputLabel: "Enter email address",
    phonePlaceholder: "98765 43210",
    emailPlaceholder: "your.name@email.com",
    sendSummary: "Send Summary",
    phoneError: "Please enter a valid 10-digit mobile number",
    emailError: "Please enter a valid email address",
    selectAtLeastOne: "Please select at least one option",

    // Share success
    shareSuccessTitle: "Summary shared successfully",
    successDoctorLine: "Doctor — via ABHA",
    successPatientLine: "Patient — via WhatsApp / Email",
    avatarShareSuccessClosing:
      "Done! Your summary has been shared. Take care of your health. Thank you!",

    // Closing (no)
    avatarClosingNo:
      "Alright. Thank you! Your report summary has been shared with your doctor. Have a good day.",
    closingNoTitle: "Have a wonderful day",

    autoResetNote: "Returning to welcome screen in {n}s",
    prototypeControls: "Prototype Controls",
    prototypeNote: "(demo only — hidden on a real kiosk)",
  },
} as const satisfies Record<Lang, Record<string, string>>;

export type TranslationKey = keyof (typeof translations)["hi"];
