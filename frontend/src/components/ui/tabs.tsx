import { Tabs as T } from "radix-ui";
import { cn } from "@/lib/utils";

export const Tabs = T.Root;
export function TabsList({ className, ...p }: React.ComponentProps<typeof T.List>) {
  return <T.List className={cn("flex items-center gap-1 border-b border-border overflow-x-auto scrollbar-thin", className)} {...p} />;
}
export function TabsTrigger({ className, ...p }: React.ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn("relative -mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-[13px] font-medium text-muted transition-colors hover:text-foreground data-[state=active]:border-accent data-[state=active]:text-foreground cursor-pointer", className)}
      {...p}
    />
  );
}
export const TabsContent = ({ className, ...p }: React.ComponentProps<typeof T.Content>) => <T.Content className={cn("pt-4 focus:outline-none", className)} {...p} />;
