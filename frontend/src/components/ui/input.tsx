import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn("h-9 w-full rounded-lg border border-border-strong bg-surface px-3 text-sm placeholder:text-subtle focus:outline-none focus:ring-2 focus:ring-ring/40", className)} {...p} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn("w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm placeholder:text-subtle focus:outline-none focus:ring-2 focus:ring-ring/40", className)} {...p} />
));
Textarea.displayName = "Textarea";

export function Select({ className, children, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn("h-9 max-w-full rounded-lg border border-border-strong bg-surface px-2.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring/40", className)} {...p}>
      {children}
    </select>
  );
}
export function Label({ className, ...p }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("block text-[12.5px] font-medium text-muted", className)} {...p} />;
}
