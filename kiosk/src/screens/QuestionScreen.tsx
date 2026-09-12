import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { KioskLayout } from "../components/KioskLayout";
import { Avatar } from "../components/Avatar";
import { AvatarSpeechBubble } from "../components/AvatarSpeechBubble";
import { DotLoader } from "../components/ProcessingAnimation";
import { QuestionProgress } from "../components/QuestionCard";
import { useLanguage } from "../i18n/LanguageContext";
import { useKiosk } from "../state/useKioskFlow";
import { usePipeline } from "../state/PipelineContext";

const CONFIRM_DELAY = 1200;
const ASK_SAFETY = 6000; // fall through to answering even if narration end never fires

export function QuestionScreen() {
  const { t } = useLanguage();
  const kiosk = useKiosk();
  const { questions, submitVoiceAnswer } = usePipeline();

  const total = questions.length;
  const index = kiosk.data.questionIndex; // 1-based
  const q = questions[index - 1];

  const [phase, setPhase] = useState<"asking" | "answering">("asking");
  const [isRecording, setIsRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [typedAnswer, setTypedAnswer] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [micError, setMicError] = useState<string | null>(null);

  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  // Reset per question; the avatar speaks the real question via Kokoro, then the
  // mic opens once narration ends (or after a safety timeout).
  useEffect(() => {
    setAnswer(null);
    setTypedAnswer("");
    setIsRecording(false);
    setBusy(false);
    setMicError(null);
    setPhase("asking");
    const safety = setTimeout(() => setPhase("answering"), ASK_SAFETY);
    return () => clearTimeout(safety);
  }, [index]);

  function finishAnswer(value: string) {
    setAnswer(value);
    setTimeout(() => {
      kiosk.answerQuestion(value);
      kiosk.advanceQuestion(total);
    }, CONFIRM_DELAY);
  }

  async function startRec() {
    if (isRecording || answer || phase !== "answering") return;
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      const mr = new MediaRecorder(stream, { audioBitsPerSecond: 128000 });
      chunks.current = [];
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((tk) => tk.stop());
        const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
        await transcribe(blob);
      };
      mr.start();
      recorder.current = mr;
      setIsRecording(true);
    } catch {
      setMicError(t("micBlocked"));
    }
  }

  function stopRec() {
    recorder.current?.stop();
    setIsRecording(false);
  }

  async function transcribe(blob: Blob) {
    if (!q) return;
    setBusy(true);
    try {
      const transcript = (await submitVoiceAnswer(q.id, blob)) || t("answerRecorded");
      finishAnswer(transcript);
    } catch (e) {
      setMicError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function handleTypeSubmit() {
    const v = typedAnswer.trim();
    if (!v || answer) return;
    finishAnswer(v);
  }

  if (!q) return null;

  const questionText = q.rendered_text;
  const avatarState = answer ? "success" : phase === "asking" ? "speaking" : "listening";
  const statusLabel = answer
    ? ""
    : busy
      ? t("transcribing")
      : phase === "asking"
        ? t("askingQuestion")
        : isRecording
          ? t("recordingAnswer")
          : t("listening");

  return (
    <KioskLayout
      avatarSlot={
        <div className="flex flex-col items-center gap-2 pt-2">
          <Avatar state={avatarState} size={100} />
          <p className="text-xs font-semibold text-primary-dark">{statusLabel}</p>
          <AnimatePresence mode="wait">
            <AvatarSpeechBubble
              key={index}
              text={questionText}
              onNarrationEnd={() => setPhase("answering")}
            />
          </AnimatePresence>
        </div>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-2">
        <QuestionProgress index={index} total={total} />

        <p className="text-xs font-bold uppercase tracking-wide text-text-secondary">
          {t("questionOf", { n: index, total })}
        </p>

        <AnimatePresence mode="wait">
          {phase === "asking" && !answer ? (
            <motion.div
              key={`asking-${index}`}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex w-full flex-col items-center gap-3 rounded-3xl bg-white p-6 shadow-lg"
            >
              <DotLoader />
              <p className="text-xs font-medium text-text-secondary">{t("askingQuestion")}</p>
            </motion.div>
          ) : answer ? (
            <motion.div
              key={`answered-${index}`}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex w-full flex-col items-center gap-2 rounded-3xl bg-white p-6 text-center shadow-lg"
            >
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 350, damping: 16 }}
                className="flex h-9 w-9 items-center justify-center rounded-full bg-success"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path d="M5 13l4 4L19 7" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </motion.div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-text-secondary">{t("yourAnswer")}</p>
              <p className="text-base font-semibold text-text-primary">{answer}</p>
            </motion.div>
          ) : (
            <motion.div
              key={`input-${index}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex w-full flex-col items-center gap-4 rounded-3xl bg-white p-5 shadow-lg"
            >
              <button
                type="button"
                onClick={isRecording ? stopRec : startRec}
                disabled={busy}
                className="flex flex-col items-center gap-2"
              >
                <span className="relative flex h-16 w-16 items-center justify-center rounded-full bg-primary-green shadow-lg shadow-primary-green/30">
                  {isRecording && (
                    <>
                      <motion.span
                        className="absolute inset-0 rounded-full bg-primary-green/40"
                        animate={{ scale: [1, 1.6], opacity: [0.6, 0] }}
                        transition={{ duration: 1.2, repeat: Infinity, ease: "easeOut" }}
                      />
                      <motion.span
                        className="absolute inset-0 rounded-full bg-primary-green/30"
                        animate={{ scale: [1, 1.9], opacity: [0.5, 0] }}
                        transition={{ duration: 1.2, repeat: Infinity, ease: "easeOut", delay: 0.4 }}
                      />
                    </>
                  )}
                  <MicIcon />
                </span>
                <span className="text-xs font-semibold text-primary-dark">
                  {busy ? t("transcribing") : isRecording ? t("tapToStop") : t("tapMicToSpeak")}
                </span>
              </button>

              {!isRecording && !busy && (
                <>
                  <div className="flex w-full items-center gap-2">
                    <span className="h-px flex-1 bg-mint-2" />
                    <span className="text-[11px] font-medium uppercase text-text-secondary">{t("orDivider")}</span>
                    <span className="h-px flex-1 bg-mint-2" />
                  </div>

                  <div className="flex w-full items-center gap-2 rounded-2xl border-2 border-primary-dark/10 bg-white px-3 py-2 focus-within:border-primary-green">
                    <input
                      type="text"
                      value={typedAnswer}
                      onChange={(e) => setTypedAnswer(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleTypeSubmit()}
                      placeholder={t("typePlaceholder")}
                      className="w-full bg-transparent text-sm font-medium text-text-primary outline-none placeholder:text-text-secondary/50"
                    />
                    <button
                      type="button"
                      onClick={handleTypeSubmit}
                      disabled={!typedAnswer.trim()}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-dark disabled:opacity-30"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <path d="M4 20l16-8L4 4v6l10 2-10 2v6Z" fill="white" />
                      </svg>
                    </button>
                  </div>
                </>
              )}

              {micError && <p className="text-xs font-medium text-danger">{micError}</p>}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </KioskLayout>
  );
}

function MicIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <rect x="9" y="2" width="6" height="12" rx="3" fill="white" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
