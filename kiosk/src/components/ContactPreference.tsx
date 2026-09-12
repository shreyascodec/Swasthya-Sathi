import { motion } from "framer-motion";
import type { ReactNode } from "react";

export function ContactPreferenceOption({
  icon,
  label,
  checked,
  onToggle,
}: {
  icon: ReactNode;
  label: string;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.98 }}
      onClick={onToggle}
      className={`flex w-full items-center gap-3 rounded-2xl border-2 px-4 py-3.5 text-left transition-colors ${
        checked ? "border-primary-green bg-mint" : "border-primary-dark/10 bg-white"
      }`}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white shadow-sm">{icon}</div>
      <span className="flex-1 text-base font-semibold text-text-primary">{label}</span>
      <div
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md border-2 ${
          checked ? "border-primary-green bg-primary-green" : "border-primary-dark/20 bg-white"
        }`}
      >
        {checked && (
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
            <path d="M5 13l4 4L19 7" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
    </motion.button>
  );
}

export function WhatsAppIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
      <path
        d="M12 2a10 10 0 0 0-8.6 15L2 22l5.2-1.4A10 10 0 1 0 12 2Z"
        fill="#25D366"
      />
      <path
        d="M8.5 7.5c.3-.6.5-.6.8-.6h.6c.2 0 .4 0 .6.5.2.5.7 1.7.7 1.9.1.1.1.3 0 .4-.1.2-.1.3-.3.5l-.4.4c-.1.1-.3.3-.1.6.2.3.8 1.3 1.7 2.1 1.2 1 2.1 1.4 2.4 1.5.3.1.5.1.6-.1l.6-.7c.2-.3.4-.2.6-.1l1.6.8c.2.1.4.2.4.4 0 .2 0 1-.4 1.4-.4.5-1.2.9-2 .9-.7 0-2.4-.3-4.4-2.1-2.4-2.1-3.3-4.2-3.4-4.9-.1-.7 0-1.6.2-2.1Z"
        fill="white"
      />
    </svg>
  );
}

export function EmailIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
      <rect x="2" y="4" width="20" height="16" rx="3" fill="#EAF7EF" stroke="#0F5C55" strokeWidth="1.6" />
      <path d="M3.5 6.5 12 13l8.5-6.5" stroke="#0F5C55" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
