import { motion } from "framer-motion";
import { QRCodeSVG } from "qrcode.react";

export function QRCodeCard({ size = 172 }: { size?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="relative rounded-2xl bg-white p-3 shadow-xl"
    >
      <div className="rounded-xl border-2 border-dashed border-secondary-green/60 p-2">
        <QRCodeSVG
          value="https://swasthyasakhi.demo/upload/SESSION-DEMO-8842"
          size={size}
          fgColor="#0F5C55"
          bgColor="#FFFFFF"
          level="M"
        />
      </div>
      {/* corner accents */}
      <span className="absolute left-1.5 top-1.5 h-4 w-4 rounded-tl-lg border-l-4 border-t-4 border-primary-green" />
      <span className="absolute right-1.5 top-1.5 h-4 w-4 rounded-tr-lg border-r-4 border-t-4 border-primary-green" />
      <span className="absolute bottom-1.5 left-1.5 h-4 w-4 rounded-bl-lg border-b-4 border-l-4 border-primary-green" />
      <span className="absolute bottom-1.5 right-1.5 h-4 w-4 rounded-br-lg border-b-4 border-r-4 border-primary-green" />
    </motion.div>
  );
}
