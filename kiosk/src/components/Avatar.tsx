import { motion } from "framer-motion";
import type { AvatarState } from "../types";
import avatarPhoto from "../assets/avatar.jpg";

interface Props {
  state: AvatarState;
  size?: number;
  /** "photo" = plain static portrait (Welcome screen only). "digital" = animated AI-avatar treatment used everywhere else. */
  variant?: "photo" | "digital";
}

const glowByState: Record<AvatarState, string> = {
  idle: "from-secondary-green/40 to-primary-green/10",
  greeting: "from-primary-green/60 to-secondary-green/20",
  speaking: "from-primary-green/70 to-primary-green/10",
  listening: "from-primary-dark/50 to-secondary-green/20",
  processing: "from-primary-green/60 to-mint/40",
  success: "from-success/70 to-secondary-green/20",
  closing: "from-secondary-green/50 to-mint/30",
};

// Every avatar size below was authored against this reference kiosk-frame width (px).
// On the small preview this renders at ~the same size as before; on the real, much
// wider physical kiosk screen it scales up proportionally instead of staying tiny.
const REFERENCE_FRAME_WIDTH = 400;

/** Converts a "designed at 400px-wide frame" pixel size into a size that scales with the actual kiosk frame width. */
function responsive(px: number, minRatio = 0.6, maxRatio = 2.6) {
  const cqw = (px / REFERENCE_FRAME_WIDTH) * 100;
  return `clamp(${px * minRatio}px, ${cqw}cqw, ${px * maxRatio}px)`;
}

export function Avatar({ state, size = 168, variant = "digital" }: Props) {
  const isDigital = variant === "digital";
  const dimension = responsive(size);
  const badgeSize = responsive(size * 0.26, 0.6, 2.2);
  const badgeIconSize = responsive(size * 0.14, 0.6, 2.2);
  const ringInset = responsive(size * 0.035, 0.6, 2.6);

  return (
    <div className="relative flex items-center justify-center" style={{ width: dimension, height: dimension }}>
      {/* soft glow ring */}
      <motion.div
        className={`absolute inset-0 rounded-full bg-gradient-to-br ${glowByState[state]} blur-xl`}
        animate={{ scale: [1, 1.08, 1], opacity: [0.6, 0.95, 0.6] }}
        transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* digital AI halo ring */}
      {isDigital && (
        <motion.div
          className="absolute rounded-full"
          style={{
            inset: `calc(-1 * ${ringInset})`,
            background:
              "conic-gradient(from 0deg, transparent 0%, #36B878 12%, transparent 24%, transparent 50%, #0F5C55 62%, transparent 74%, transparent 100%)",
            padding: 2,
            WebkitMask: "linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)",
            WebkitMaskComposite: "xor",
            maskComposite: "exclude",
          }}
          animate={{ rotate: 360 }}
          transition={{ duration: 6, repeat: Infinity, ease: "linear" }}
        />
      )}

      {/* avatar body */}
      <div className="relative" style={{ width: dimension, height: dimension }}>
        <div
          className="relative overflow-hidden rounded-full bg-white shadow-xl"
          style={{ width: dimension, height: dimension }}
        >
          <img
            src={avatarPhoto}
            alt="Swasthya Sakhi"
            className="h-full w-full object-cover"
            style={{ objectPosition: "50% 22%" }}
          />

          {isDigital && (
            <>
              {/* holographic tint */}
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary-green/10 via-transparent to-primary-dark/10" />
              {/* scan line sweep */}
              <motion.div
                className="pointer-events-none absolute left-0 right-0 h-1/3 bg-gradient-to-b from-transparent via-white/40 to-transparent"
                animate={{ top: ["-40%", "110%"] }}
                transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut", repeatDelay: 0.6 }}
              />
            </>
          )}
        </div>

        {/* listening waveform */}
        {state === "listening" && (
          <div className="absolute -bottom-2 left-1/2 flex -translate-x-1/2 items-end gap-[3px] rounded-full bg-white px-2.5 py-1.5 shadow-md">
            {[0, 1, 2, 3, 4].map((i) => (
              <motion.span
                key={i}
                className="w-[3px] rounded-full bg-primary-dark"
                style={{ height: 12 }}
                animate={{ scaleY: [0.4, 1, 0.4] }}
                transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.12, ease: "easeInOut" }}
              />
            ))}
          </div>
        )}

        {/* processing spinner ring */}
        {state === "processing" && (
          <motion.div
            className="absolute -bottom-1 -right-1 flex items-center justify-center rounded-full bg-white shadow-md"
            style={{ width: badgeSize, height: badgeSize }}
            animate={{ rotate: 360 }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }}
          >
            <svg width={badgeIconSize} height={badgeIconSize} viewBox="0 0 24 24" fill="none">
              <path
                d="M12 3a9 9 0 1 0 9 9"
                stroke="#36B878"
                strokeWidth="2.6"
                strokeLinecap="round"
              />
            </svg>
          </motion.div>
        )}

        {/* success check */}
        {state === "success" && (
          <motion.div
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 15 }}
            className="absolute -bottom-1 -right-1 flex items-center justify-center rounded-full bg-success shadow-md"
            style={{ width: badgeSize, height: badgeSize }}
          >
            <svg width={badgeIconSize} height={badgeIconSize} viewBox="0 0 24 24" fill="none">
              <path d="M5 13l4 4L19 7" stroke="white" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </motion.div>
        )}
      </div>
    </div>
  );
}
