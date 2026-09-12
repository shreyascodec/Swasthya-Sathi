import logoImg from "../assets/logo.png";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <img
      src={logoImg}
      alt="Swasthya Sakhi"
      className={compact ? "h-11 w-auto object-contain" : "h-14 w-auto object-contain"}
    />
  );
}
