import { Logo } from "./Logo";
import { LanguageSelector } from "./LanguageSelector";

export function Navbar() {
  return (
    <div className="flex shrink-0 items-center justify-between gap-2 px-4 pt-5 pb-3">
      <Logo compact />
      <LanguageSelector />
    </div>
  );
}
