import { forwardRef } from "react";
import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Base `<input>` primitive with standard border/focus-ring styling. Forwards `ref` and all native input props. */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-lg border border-input bg-card px-3.5 py-2 text-sm",
        "placeholder:text-muted-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-ring",
        "disabled:opacity-50 disabled:cursor-not-allowed transition-colors",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";

/** Base `<textarea>` primitive matching `Input`'s styling (non-resizable). Forwards `ref` and all native textarea props. */
export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex w-full rounded-lg border border-input bg-card px-3.5 py-2.5 text-sm",
      "placeholder:text-muted-foreground resize-none",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-ring",
      "disabled:opacity-50 disabled:cursor-not-allowed transition-colors",
      className
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
