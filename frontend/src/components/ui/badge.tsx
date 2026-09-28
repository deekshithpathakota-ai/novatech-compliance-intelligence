import * as React from "react";
import { cn } from "@/lib/utils";

export const tones = {
  neutral: "bg-surface-2 text-muted border-border",
  info: "bg-info-soft text-info border-transparent",
  accent: "bg-accent-soft text-accent border-transparent",
  success: "bg-success-soft text-success border-transparent",
  warning: "bg-warning-soft text-warning border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  critical: "bg-critical-soft text-critical border-transparent",
  navy: "bg-primary text-primary-foreground border-transparent",
};
export type Tone = keyof typeof tones;

export function Badge({ tone = "neutral", className, dot, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone; dot?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide whitespace-nowrap", tones[tone], className)} {...p}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />}
      {p.children}
    </span>
  );
}
