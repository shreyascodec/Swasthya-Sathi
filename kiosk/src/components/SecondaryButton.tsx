import { motion } from "framer-motion";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type ConflictingProps = "onAnimationStart" | "onDrag" | "onDragStart" | "onDragEnd";

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, ConflictingProps> {
  children: ReactNode;
  fullWidth?: boolean;
}

export function SecondaryButton({ children, fullWidth = true, className = "", ...rest }: Props) {
  return (
    <motion.button
      whileTap={{ scale: 0.97 }}
      className={`${fullWidth ? "w-full" : ""} rounded-2xl border-2 border-primary-dark/15 bg-white px-6 py-4 text-base font-bold text-primary-dark shadow-sm transition-colors active:bg-mint ${className}`}
      {...rest}
    >
      {children}
    </motion.button>
  );
}
