import { Dialog as D } from "radix-ui";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({ className, title, description, children, side }: {
  className?: string; title: React.ReactNode; description?: React.ReactNode; children: React.ReactNode; side?: "right";
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[1px] data-[state=open]:nt-in" />
      <D.Content
        className={cn(
          "fixed z-50 bg-surface border border-border shadow-pop focus:outline-none flex flex-col",
          side === "right"
            ? "right-0 top-0 h-full w-full max-w-[560px] border-l"
            : "left-1/2 top-1/2 w-[calc(100%-32px)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl max-h-[88vh]",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <D.Title className="text-[15px] font-semibold">{title}</D.Title>
            {description ? <D.Description className="mt-0.5 text-[12.5px] text-muted">{description}</D.Description> : <D.Description className="sr-only">Details</D.Description>}
          </div>
          <D.Close className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-foreground cursor-pointer" aria-label="Close"><X className="h-4 w-4" /></D.Close>
        </div>
        <div className="overflow-y-auto scrollbar-thin px-5 py-4">{children}</div>
      </D.Content>
    </D.Portal>
  );
}
