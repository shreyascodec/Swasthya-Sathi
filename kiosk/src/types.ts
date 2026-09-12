export type Lang = "hi" | "en";

export type ScreenState =
  | "WELCOME"
  | "IDENTIFY"
  | "ID_ENTRY"
  | "ID_VERIFY"
  | "QR_UPLOAD"
  | "PROCESSING_REPORT"
  | "QUESTIONS"
  | "GENERATING_SUMMARY"
  | "SUMMARY"
  | "SHARE_CHOICE"
  | "CONTACT_DETAILS"
  | "SHARE_SUCCESS"
  | "CLOSING";

export type AvatarState =
  | "idle"
  | "greeting"
  | "speaking"
  | "listening"
  | "processing"
  | "success"
  | "closing";

export type YesNo = "yes" | "no";

export type IdType = "abha" | "aadhaar" | null;

export interface QuestionAnswer {
  questionId: number;
  /** Free-text patient response, captured via mic (voice) or typed input. */
  value: string;
}

export interface ContactInfo {
  useWhatsapp: boolean;
  useEmail: boolean;
  phone: string;
  email: string;
}

export interface KioskData {
  mobileUploadOpen: boolean;
  uploaded: boolean;
  questionIndex: number; // 1-5
  answers: QuestionAnswer[];
  shareChoice: YesNo | null;
  contact: ContactInfo;
  idType: IdType;
  idNumber: string;
  idVerified: boolean;
}
