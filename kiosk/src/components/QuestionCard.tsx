import { motion } from "framer-motion";

export function QuestionProgress({ index, total = 5 }: { index: number; total?: number }) {
  const steps = Array.from({ length: Math.max(total, 1) }, (_, i) => i + 1);
  return (
    <div className="flex items-center justify-center gap-2">
      {steps.map((n) => (
        <div key={n} className="flex flex-col items-center gap-1">
          <motion.div
            animate={{
              scale: n === index ? 1.15 : 1,
              backgroundColor: n < index ? "#36B878" : n === index ? "#0F5C55" : "#DCF2E4",
            }}
            transition={{ duration: 0.3 }}
            className="flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold text-white"
          >
            {n < index ? (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                <path d="M5 13l4 4L19 7" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <span className={n === index ? "text-white" : "text-primary-dark/50"}>{n}</span>
            )}
          </motion.div>
        </div>
      ))}
    </div>
  );
}
