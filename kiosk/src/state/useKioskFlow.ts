import { createContext, useCallback, useContext, useMemo, useReducer } from "react";
import type { ContactInfo, IdType, KioskData, ScreenState, YesNo } from "../types";

interface KioskState {
  screen: ScreenState;
  data: KioskData;
}

const initialData: KioskData = {
  mobileUploadOpen: false,
  uploaded: false,
  questionIndex: 1,
  answers: [],
  shareChoice: null,
  contact: { useWhatsapp: true, useEmail: false, phone: "", email: "" },
  idType: null,
  idNumber: "",
  idVerified: false,
};

const initialState: KioskState = {
  screen: "WELCOME",
  data: initialData,
};

type Action =
  | { type: "START" }
  | { type: "CHOOSE_ID_TYPE"; idType: Exclude<IdType, null> }
  | { type: "SKIP_ID" }
  | { type: "SUBMIT_ID_NUMBER"; value: string }
  | { type: "ID_VERIFIED" }
  | { type: "OPEN_MOBILE_UPLOAD" }
  | { type: "CLOSE_MOBILE_UPLOAD" }
  | { type: "MOBILE_UPLOAD_COMPLETE" }
  | { type: "PROCESSING_DONE" }
  | { type: "SKIP_QUESTIONS" }
  | { type: "ANSWER_QUESTION"; value: string }
  | { type: "QUESTIONS_DONE"; total: number }
  | { type: "SUMMARY_READY" }
  | { type: "CONTINUE_FROM_SUMMARY" }
  | { type: "CHOOSE_SHARE"; value: YesNo }
  | { type: "UPDATE_CONTACT"; contact: Partial<ContactInfo> }
  | { type: "SUBMIT_CONTACT" }
  | { type: "RESET" };

function reducer(state: KioskState, action: Action): KioskState {
  switch (action.type) {
    case "START":
      return { ...state, screen: "IDENTIFY" };
    case "CHOOSE_ID_TYPE":
      return {
        ...state,
        screen: "ID_ENTRY",
        data: { ...state.data, idType: action.idType, idNumber: "", idVerified: false },
      };
    case "SKIP_ID":
      return {
        ...state,
        screen: "QR_UPLOAD",
        data: { ...state.data, idType: null, idNumber: "", idVerified: false },
      };
    case "SUBMIT_ID_NUMBER":
      return { ...state, screen: "ID_VERIFY", data: { ...state.data, idNumber: action.value } };
    case "ID_VERIFIED":
      return { ...state, screen: "QR_UPLOAD", data: { ...state.data, idVerified: true } };
    case "OPEN_MOBILE_UPLOAD":
      return { ...state, data: { ...state.data, mobileUploadOpen: true } };
    case "CLOSE_MOBILE_UPLOAD":
      return { ...state, data: { ...state.data, mobileUploadOpen: false } };
    case "MOBILE_UPLOAD_COMPLETE":
      return {
        ...state,
        screen: "PROCESSING_REPORT",
        data: { ...state.data, mobileUploadOpen: false, uploaded: true },
      };
    case "PROCESSING_DONE":
      return { ...state, screen: "QUESTIONS", data: { ...state.data, questionIndex: 1 } };
    case "SKIP_QUESTIONS":
      // A valid report with no grounded intake questions — go straight to the
      // summary generation step, skipping the interview.
      return { ...state, screen: "GENERATING_SUMMARY" };
    case "ANSWER_QUESTION": {
      const answers = [
        ...state.data.answers,
        { questionId: state.data.questionIndex, value: action.value },
      ];
      return { ...state, data: { ...state.data, answers } };
    }
    case "QUESTIONS_DONE":
      if (state.data.questionIndex >= action.total) {
        return { ...state, screen: "GENERATING_SUMMARY" };
      }
      return { ...state, data: { ...state.data, questionIndex: state.data.questionIndex + 1 } };
    case "SUMMARY_READY":
      return { ...state, screen: "SUMMARY" };
    case "CONTINUE_FROM_SUMMARY":
      return { ...state, screen: "SHARE_CHOICE" };
    case "CHOOSE_SHARE":
      if (action.value === "no") {
        return { ...state, screen: "CLOSING", data: { ...state.data, shareChoice: "no" } };
      }
      return { ...state, screen: "CONTACT_DETAILS", data: { ...state.data, shareChoice: "yes" } };
    case "UPDATE_CONTACT":
      return { ...state, data: { ...state.data, contact: { ...state.data.contact, ...action.contact } } };
    case "SUBMIT_CONTACT":
      return { ...state, screen: "SHARE_SUCCESS" };
    case "RESET":
      return { screen: "WELCOME", data: initialData };
    default:
      return state;
  }
}

interface KioskContextValue {
  screen: ScreenState;
  data: KioskData;
  start: () => void;
  chooseIdType: (idType: Exclude<IdType, null>) => void;
  skipId: () => void;
  submitIdNumber: (value: string) => void;
  idVerified: () => void;
  openMobileUpload: () => void;
  closeMobileUpload: () => void;
  completeMobileUpload: () => void;
  processingDone: () => void;
  skipQuestions: () => void;
  answerQuestion: (value: string) => void;
  advanceQuestion: (total: number) => void;
  summaryReady: () => void;
  continueFromSummary: () => void;
  chooseShare: (value: YesNo) => void;
  updateContact: (contact: Partial<ContactInfo>) => void;
  submitContact: () => void;
  reset: () => void;
}

export const KioskContext = createContext<KioskContextValue | null>(null);

export function useKioskFlowState(): KioskContextValue {
  const [state, dispatch] = useReducer(reducer, initialState);

  const start = useCallback(() => dispatch({ type: "START" }), []);
  const chooseIdType = useCallback(
    (idType: Exclude<IdType, null>) => dispatch({ type: "CHOOSE_ID_TYPE", idType }),
    []
  );
  const skipId = useCallback(() => dispatch({ type: "SKIP_ID" }), []);
  const submitIdNumber = useCallback((value: string) => dispatch({ type: "SUBMIT_ID_NUMBER", value }), []);
  const idVerified = useCallback(() => dispatch({ type: "ID_VERIFIED" }), []);
  const openMobileUpload = useCallback(() => dispatch({ type: "OPEN_MOBILE_UPLOAD" }), []);
  const closeMobileUpload = useCallback(() => dispatch({ type: "CLOSE_MOBILE_UPLOAD" }), []);
  const completeMobileUpload = useCallback(() => dispatch({ type: "MOBILE_UPLOAD_COMPLETE" }), []);
  const processingDone = useCallback(() => dispatch({ type: "PROCESSING_DONE" }), []);
  const skipQuestions = useCallback(() => dispatch({ type: "SKIP_QUESTIONS" }), []);
  const answerQuestion = useCallback((value: string) => dispatch({ type: "ANSWER_QUESTION", value }), []);
  const advanceQuestion = useCallback((total: number) => dispatch({ type: "QUESTIONS_DONE", total }), []);
  const summaryReady = useCallback(() => dispatch({ type: "SUMMARY_READY" }), []);
  const continueFromSummary = useCallback(() => dispatch({ type: "CONTINUE_FROM_SUMMARY" }), []);
  const chooseShare = useCallback((value: YesNo) => dispatch({ type: "CHOOSE_SHARE", value }), []);
  const updateContact = useCallback(
    (contact: Partial<ContactInfo>) => dispatch({ type: "UPDATE_CONTACT", contact }),
    []
  );
  const submitContact = useCallback(() => dispatch({ type: "SUBMIT_CONTACT" }), []);
  const reset = useCallback(() => dispatch({ type: "RESET" }), []);

  return useMemo(
    () => ({
      screen: state.screen,
      data: state.data,
      start,
      chooseIdType,
      skipId,
      submitIdNumber,
      idVerified,
      openMobileUpload,
      closeMobileUpload,
      completeMobileUpload,
      processingDone,
      skipQuestions,
      answerQuestion,
      advanceQuestion,
      summaryReady,
      continueFromSummary,
      chooseShare,
      updateContact,
      submitContact,
      reset,
    }),
    [
      state,
      start,
      chooseIdType,
      skipId,
      submitIdNumber,
      idVerified,
      openMobileUpload,
      closeMobileUpload,
      completeMobileUpload,
      processingDone,
      skipQuestions,
      answerQuestion,
      advanceQuestion,
      summaryReady,
      continueFromSummary,
      chooseShare,
      updateContact,
      submitContact,
      reset,
    ]
  );
}

export function useKiosk() {
  const ctx = useContext(KioskContext);
  if (!ctx) throw new Error("useKiosk must be used within KioskContext.Provider");
  return ctx;
}
