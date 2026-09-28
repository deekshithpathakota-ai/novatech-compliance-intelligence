import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export function fmtDate(v?: string | null, opts: Intl.DateTimeFormatOptions = { day: "2-digit", month: "short", year: "numeric" }) {
  if (!v) return "—";
  const d = new Date(v.length === 10 ? v + "T00:00:00" : v);
  return isNaN(d.getTime()) ? "—" : d.toLocaleDateString("en-GB", opts);
}
export function fmtDateTime(v?: string | null) {
  if (!v) return "—";
  return new Date(v).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function relDays(v?: string | null) {
  if (!v) return "—";
  const d = Math.round((new Date(v).getTime() - Date.now()) / 86400000);
  if (d === 0) return "today";
  return d > 0 ? `in ${d}d` : `${-d}d ago`;
}
export const title = (s?: string | null) =>
  (s ?? "").toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function withViewTransition(fn: () => void) {
  const d = document as Document & { startViewTransition?: (cb: () => void) => void };
  if (d.startViewTransition && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) d.startViewTransition(fn);
  else fn();
}
