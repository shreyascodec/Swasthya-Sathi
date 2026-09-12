import { motion, AnimatePresence } from "framer-motion";
import { useEffect } from "react";
import { useLanguage } from "../i18n/LanguageContext";
import { speakText, stopSpeech } from "../utils/speech";

interface Props {
  text: string;
  voiceOver?: boolean;
  /** Called once the narration for this text has finished playing (or immediately if voiceOver is off). */
  onNarrationEnd?: () => void;
}

export function AvatarSpeechBubble({ text, voiceOver = true, onNarrationEnd }: Props) {
  const { lang } = useLanguage();

  useEffect(() => {
    if (!voiceOver) {
      onNarrationEnd?.();
      return;
    }
    let cancelled = false;
    speakText(text, lang).then(() => {
      if (!cancelled) onNarrationEnd?.();
    });
    return () => {
      cancelled = true;
      stopSpeech();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, lang, voiceOver]);

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={text}
        initial={{ opacity: 0, y: 8, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.35 }}
        className="relative mx-auto max-w-xs rounded-2xl bg-white px-4 py-3 text-center text-sm font-medium leading-snug text-text-primary shadow-md"
      >
        <span className="absolute -top-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rotate-45 rounded-[2px] bg-white" />
        {text}
      </motion.div>
    </AnimatePresence>
  );
}
