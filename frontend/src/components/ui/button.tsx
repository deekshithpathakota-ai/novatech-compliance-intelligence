import * as React from "react";
import { cn } from "@/lib/utils";

const variants = {
  primary: "bg-primary text-primary-foreground hover:opacity-90 shadow-sm",
  accent: "bg-accent text-accent-foreground hover:opacity-90 shadow-sm",
  secondary: "bg-surface text-foreground border border-border-strong hover:bg-surface-2",
  ghost: "text-muted hover:text-foreground hover:bg-surface-2",
  danger: "bg-danger text-white hover:opacity-90",
  success: "bg-success text-white hover:opacity-90",
  link: "text-accent hover:underline px-0 h-auto",
};
const sizes = { sm: "h-8 px-3 text-[13px] gap-1.5", md: "h-9 px-3.5 text-sm gap-2", lg: "h-11 px-5 text-[15px] gap-2", icon: "h-9 w-9" };

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "secondary", size = "md", loading, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center rounded-lg font-medium whitespace-nowrap transition-colors disabled:opacity-50 disabled:pointer-events-none cursor-pointer",
        variants[variant], sizes[size], className,
      )}
      {...props}
    >
      {loading && <span className="h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" aria-hidden />}
      {children}
    </button>
  ),
);
Button.displayName = "Button";
