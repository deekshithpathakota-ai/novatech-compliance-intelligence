import { DropdownMenu as DM, Tooltip as TT } from "radix-ui";
import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("nt-skeleton rounded-md", className)} aria-hidden />;
}

export function Progress({ value, tone = "accent", className }: { value: number; tone?: "accent" | "success" | "warning" | "danger"; className?: string }) {
  const color = { accent: "bg-accent", success: "bg-success", warning: "bg-warning", danger: "bg-danger" }[tone];
  return (
    <div className={cn("h-1.5 w-full rounded-full bg-surface-2 overflow-hidden", className)} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", color)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export const Menu = DM.Root;
export const MenuTrigger = DM.Trigger;
export function MenuContent({ className, ...p }: React.ComponentProps<typeof DM.Content>) {
  return (
    <DM.Portal>
      <DM.Content sideOffset={6} className={cn("z-50 min-w-[220px] rounded-xl border border-border bg-surface p-1 shadow-pop nt-in", className)} {...p} />
    </DM.Portal>
  );
}
export function MenuItem({ className, ...p }: React.ComponentProps<typeof DM.Item>) {
  return <DM.Item className={cn("flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] outline-none data-[highlighted]:bg-surface-2", className)} {...p} />;
}
export const MenuLabel = ({ className, ...p }: React.ComponentProps<typeof DM.Label>) => <DM.Label className={cn("px-2.5 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle", className)} {...p} />;
export const MenuSeparator = () => <DM.Separator className="my-1 h-px bg-border" />;

export function Tip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <TT.Provider delayDuration={250}>
      <TT.Root>
        <TT.Trigger asChild>{children}</TT.Trigger>
        <TT.Portal>
          <TT.Content sideOffset={6} className="z-50 max-w-xs rounded-lg bg-primary px-2.5 py-1.5 text-[12px] text-primary-foreground shadow-pop">{content}</TT.Content>
        </TT.Portal>
      </TT.Root>
    </TT.Provider>
  );
}
