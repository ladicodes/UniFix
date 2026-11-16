import type { CategoryId, Currency, RatingBreakdown, RatingKey } from "./types";

/** Indicative local-currency units per 1 USDC. Shown to users as an estimate. */
export const RATES: Record<Currency, number> = { NGN: 1550, GHS: 15.4 };

/** Estimated Stellar network fee for an escrow call, in XLM. */
export const NETWORK_FEE_XLM = 0.00421;

export const CATEGORIES: { id: CategoryId; label: string; plural: string }[] = [
  { id: "electrician", label: "Electrician", plural: "Electricians" },
  { id: "plumber", label: "Plumber", plural: "Plumbers" },
  { id: "ac-technician", label: "AC technician", plural: "AC technicians" },
  { id: "mechanic", label: "Mechanic", plural: "Mechanics" },
  { id: "generator", label: "Generator repair", plural: "Generator repairers" },
  { id: "carpenter", label: "Carpenter", plural: "Carpenters" },
  { id: "cleaner", label: "Cleaner", plural: "Cleaners" },
  { id: "painter", label: "Painter", plural: "Painters" },
];

export function categoryLabel(id: CategoryId) {
  return CATEGORIES.find((c) => c.id === id)?.label ?? id;
}

export const RATING_LABELS: Record<RatingKey, string> = {
  quality: "Quality of work",
  punctuality: "Punctuality",
  communication: "Communication",
  professionalism: "Professionalism",
  value: "Value for money",
};

export function overall(r: RatingBreakdown) {
  const v = (r.quality + r.punctuality + r.communication + r.professionalism + r.value) / 5;
  return Math.round(v * 10) / 10;
}

export function money(amount: number, currency: Currency) {
  return new Intl.NumberFormat(currency === "NGN" ? "en-NG" : "en-GH", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function usdc(amount: number) {
  return `${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDC`;
}

export function toUsdc(local: number, currency: Currency) {
  return Math.round((local / RATES[currency]) * 100) / 100;
}

export function shortAddress(a?: string) {
  if (!a) return "";
  return `${a.slice(0, 5)}…${a.slice(-5)}`;
}

export function shortHash(h?: string) {
  if (!h) return "";
  return `${h.slice(0, 8)}…${h.slice(-6)}`;
}

export function timeAgo(iso: string) {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} d ago`;
  return shortDate(iso);
}

export function shortDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(iso: string) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function clockTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function initials(name: string) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}
