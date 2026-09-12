import type { ReactNode } from "react";

export function KioskFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-dvh w-full items-center justify-center bg-[#0b1f1c]">
      <div
        className="relative overflow-hidden bg-bg shadow-2xl"
        style={{
          width: "min(100vw, calc(100dvh * 9 / 16))",
          height: "min(100dvh, calc(100vw * 16 / 9))",
          aspectRatio: "9 / 16",
          containerType: "inline-size",
        }}
      >
        {children}
      </div>
    </div>
  );
}
