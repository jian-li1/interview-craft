"use client";

import { useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Check, ChevronDown } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/utils";

/** One selectable row in a `ChipSelect` popover. */
export interface ChipSelectOption {
  id: string;
  label: string;
  /** Optional right-aligned muted badge (e.g. a model's provider name). */
  badge?: string;
}

interface ChipSelectProps {
  icon: LucideIcon;
  options: ChipSelectOption[];
  /** Currently selected option id; null renders the chip with no highlighted row. */
  value: string | null;
  onChange: (id: string) => void;
  /** True while the host surface is disabled — makes the chip non-interactive. */
  disabled?: boolean;
  ariaLabel: string;
}

/**
 * Compact pill-button chip (model / search-provider selection, etc.) — a hand-rolled
 * select matching `src/components/ui/*`'s no-Radix style. Clicking opens an
 * upward-anchored popover (chips typically sit at the bottom of their host surface, so
 * a downward popover would run off-screen) listing `options`; closes on outside click,
 * Escape, or picking an option. Long labels are truncated so the chip row never
 * overflows/wraps awkwardly. Used by the studio composer and the dashboard prompt box.
 */
export function ChipSelect({ icon: Icon, options, value, onChange, disabled, ariaLabel }: ChipSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Closes the popover on outside click, mirroring UserMenu's pattern.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  // Closes on Escape regardless of focus target within the popover.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const selected = options.find((o) => o.id === value);
  const label = selected?.label ?? "Select…";

  return (
    // min-w-0 overrides the flex default `min-width: auto`, which otherwise pins this
    // item's minimum size to its unwrapped text width — letting the chip shrink (instead
    // of wrapping to a new line) when the composer row runs out of horizontal space.
    <div className="relative min-w-0" ref={ref}>
      <button
        type="button"
        onClick={() => !disabled && setOpen((o) => !o)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        className={cn(
          // w-full tracks this button's width to the parent's (now shrinkable) box so the
          // chip visually narrows and its label truncates, rather than overflowing.
          "flex h-7 w-full max-w-[160px] items-center gap-1.5 rounded-lg border border-border bg-transparent px-2 text-xs text-muted-foreground transition-colors",
          // accent-soft (not the vivid --accent fill) keeps hover text readable in both themes.
          "hover:bg-accent-soft hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          disabled && "pointer-events-none opacity-50"
        )}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-left">{label}</span>
        <ChevronDown className="h-3 w-3 shrink-0" aria-hidden="true" />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="listbox"
            aria-label={ariaLabel}
            initial={{ opacity: 0, y: 4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.98 }}
            transition={{ duration: 0.12 }}
            // Anchored ABOVE the chip (bottom-full) — chips typically sit at the bottom
            // of their host surface, so an ordinary downward popover would be clipped.
            className="absolute bottom-full left-0 z-20 mb-1 min-w-[190px] rounded-xl border border-border bg-popover p-1 shadow-lg"
          >
            {options.map((opt) => {
              const isSelected = opt.id === value;
              return (
                <button
                  key={opt.id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    onChange(opt.id);
                    setOpen(false);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs hover:bg-accent-soft"
                >
                  <Check
                    className={cn("h-3.5 w-3.5 shrink-0", isSelected ? "opacity-100" : "opacity-0")}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">{opt.label}</span>
                  {opt.badge && (
                    <span className="shrink-0 truncate text-[10px] uppercase tracking-wide text-muted-foreground">
                      {opt.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Friendly display labels for search provider ids — falls back to the raw id for any
// provider not listed here (forward-compatible with a new backend provider). Shared by
// the studio composer (Composer.tsx) and the dashboard prompt box (PromptBox.tsx) so
// the mapping only lives in one place.
export const SEARCH_PROVIDER_LABELS: Record<string, string> = {
  duckduckgo: "DuckDuckGo",
  google: "Google",
  tavily: "Tavily",
};
