import { motion } from "framer-motion";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type ConflictingProps = "onAnimationStart" | "onDrag" | "onDragStart" | "onDragEnd";

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, ConflictingProps> {
  children: ReactNode;
  fullWidth?: boolean;
}

export function PrimaryButton({ children, fullWidth = true, className = "", disabled, ...rest }: Props) {
  return (
    <motion.button
      whileTap={disabled ? undefined : { scale: 0.97 }}
      disabled={disabled}
      className={`${fullWidth ? "w-full" : ""} rounded-2xl bg-gradient-to-r from-primary-green to-primary-green-2 px-6 py-4 text-base font-bold text-white shadow-lg shadow-primary-green/25 transition-opacity active:opacity-90 disabled:cursor-not-allowed disabled:from-secondary-green disabled:to-secondary-green disabled:shadow-none disabled:opacity-60 ${className}`}
      {...rest}
    >
      {children}
    </motion.button>
  );
}
