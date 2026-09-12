import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { Navbar } from "./Navbar";

interface Props {
  children: ReactNode;
  /** Rendered right below the navbar, outside the scrollable area — the avatar never scrolls. */
  avatarSlot?: ReactNode;
  showNavbar?: boolean;
}

export function KioskLayout({ children, avatarSlot, showNavbar = true }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35 }}
      className="flex h-full flex-col bg-gradient-to-b from-mint to-bg"
    >
      {showNavbar && <Navbar />}
      {avatarSlot && <div className="shrink-0 px-5 pb-2 text-center">{avatarSlot}</div>}
      <div className="no-scrollbar flex flex-1 flex-col overflow-y-auto px-5 pb-6">{children}</div>
    </motion.div>
  );
}
