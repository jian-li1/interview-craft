"use client";

import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const STEP_LABELS = ["Background", "Roles & timeline", "Skills & resume", "Review"];

/**
 * Step-progress indicator for the onboarding wizard: renders `STEP_LABELS`
 * as a horizontal sequence of numbered circles connected by animated fill
 * bars. `step` is 1-indexed; each item is classified as "done" (index <
 * step, filled circle with a checkmark and a fully-animated connector),
 * "current" (index === step, outlined/highlighted), or "upcoming" (muted).
 */
export function WizardProgress({ step }: { step: number }) {
  return (
    <ol className="flex items-center gap-2 sm:gap-4" aria-label="Onboarding progress">
      {STEP_LABELS.map((label, i) => {
        const index = i + 1;
        const state = index < step ? "done" : index === step ? "current" : "upcoming";
        return (
          <li key={label} className="flex flex-1 items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                  state === "done" && "border-accent bg-accent text-accent-foreground",
                  state === "current" && "border-accent text-accent",
                  state === "upcoming" && "border-border text-muted-foreground"
                )}
                aria-current={state === "current" ? "step" : undefined}
              >
                {state === "done" ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : index}
              </span>
              <span
                className={cn(
                  "hidden text-xs font-medium sm:inline",
                  state === "upcoming" ? "text-muted-foreground" : "text-foreground"
                )}
              >
                {label}
              </span>
            </div>
            {index < STEP_LABELS.length && (
              <div className="relative h-0.5 flex-1 overflow-hidden rounded-full bg-border">
                <motion.div
                  className="absolute inset-y-0 left-0 bg-accent"
                  initial={false}
                  animate={{ width: state === "done" ? "100%" : "0%" }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
