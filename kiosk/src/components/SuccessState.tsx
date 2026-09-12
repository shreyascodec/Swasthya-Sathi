import { motion } from "framer-motion";

export function SuccessCheck({ size = 88 }: { size?: number }) {
  return (
    <motion.div
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 16 }}
      className="relative mx-auto flex items-center justify-center rounded-full bg-success shadow-lg shadow-success/30"
      style={{ width: size, height: size }}
    >
      <motion.div
        className="absolute inset-0 rounded-full bg-success/40"
        animate={{ scale: [1, 1.4], opacity: [0.5, 0] }}
        transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }}
      />
      <svg width={size * 0.45} height={size * 0.45} viewBox="0 0 24 24" fill="none">
        <motion.path
          d="M5 13l4 4L19 7"
          stroke="white"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.5, delay: 0.2, ease: "easeOut" }}
        />
      </svg>
    </motion.div>
  );
}
