import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "success" | "warning" | "destructive" | "info" | "outline";

const variantClasses: Record<Variant, string> = {
  default: "bg-accent-soft text-accent border-transparent",
  success: "bg-success/15 text-success border-transparent",
  warning: "bg-warning/15 text-warning border-transparent",
  destructive: "bg-destructive/15 text-destructive border-transparent",
  info: "bg-info/15 text-info border-transparent",
  outline: "bg-transparent text-muted-foreground border-border",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: Variant;
}

/**
 * Small pill label. `variant` selects the color treatment — "default"
 * (accent), "success", "warning", "destructive", "info" (all soft/tinted
 * backgrounds), or "outline" (transparent with a border) — via
 * `variantClasses`. Any other span props (e.g. `className`, `onClick`)
 * pass through.
 */
export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        variantClasses[variant],
        className
      )}
      {...props}
    />
  );
}
