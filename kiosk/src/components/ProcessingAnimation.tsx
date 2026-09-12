import { motion } from "framer-motion";

export function ProcessingAnimation() {
  return (
    <div className="relative mx-auto flex h-24 w-20 items-center justify-center">
      <div className="relative h-24 w-20 overflow-hidden rounded-lg border-2 border-primary-green/40 bg-white shadow-md">
        <div className="space-y-1.5 p-2.5 pt-3">
          {[85, 65, 75, 50, 70].map((w, i) => (
            <div key={i} className="h-1.5 rounded-full bg-mint-2" style={{ width: `${w}%` }} />
          ))}
        </div>
        <motion.div
          className="absolute left-0 right-0 h-[3px] bg-gradient-to-r from-transparent via-primary-green to-transparent shadow-[0_0_8px_2px_rgba(54,184,120,0.6)]"
          animate={{ top: ["4%", "94%", "4%"] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>
      <motion.div
        className="absolute -right-2 -top-2 flex h-8 w-8 items-center justify-center rounded-full bg-primary-dark text-white shadow-md"
        animate={{ rotate: 360 }}
        transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path
            d="M12 2a10 10 0 1 0 10 10"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
        </svg>
      </motion.div>
    </div>
  );
}

export function DotLoader() {
  return (
    <span className="inline-flex items-end gap-1">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1.5 w-1.5 rounded-full bg-primary-dark/60"
          animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.15, ease: "easeInOut" }}
        />
      ))}
    </span>
  );
}
