"use client";

import { useState } from "react";
import type { KeyboardEvent } from "react";
import { X } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { cn } from "@/lib/utils";

interface ChipInputProps {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  "aria-label"?: string;
  className?: string;
}

/**
 * Simple tag/chip input: type + Enter or comma to add, backspace on empty
 * to remove last. `values`/`onChange` make this a fully controlled list —
 * the component only tracks the in-progress `draft` text itself.
 */
export function ChipInput({
  values,
  onChange,
  placeholder,
  className,
  ...rest
}: ChipInputProps) {
  const [draft, setDraft] = useState("");

  // Adds `raw` (trimmed) as a new chip unless it's empty or a case-insensitive
  // duplicate of an existing chip (in which case the draft is just cleared,
  // silently, rather than adding a repeat). Used by both the Enter/comma key
  // handler and onBlur below.
  function commit(raw: string) {
    const value = raw.trim();
    if (!value) return;
    if (values.some((v) => v.toLowerCase() === value.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...values, value]);
    setDraft("");
  }

  // Enter or comma commits the current draft as a new chip. Backspace only
  // removes the last chip when the draft is empty — i.e. the first
  // Backspace press with text still in the input just edits the text
  // normally instead of deleting a chip, which is what previously caused
  // the "deleting the chip instead of the last character" onboarding bug.
  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit(draft);
    } else if (e.key === "Backspace" && draft === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  return (
    <div
      className={cn(
        "flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-lg border border-input bg-card px-2.5 py-2",
        "focus-within:ring-2 focus-within:ring-ring focus-within:border-ring",
        className
      )}
    >
      {values.map((value, index) => (
        // Each chip and its remove button call preventDefault() on
        // mousedown so clicking "X" never steals focus away from the text
        // input first (focus loss there could otherwise interact badly
        // with the draft/commit state above). Removal itself only happens
        // in onClick, filtering this chip out of `values` by index and
        // reporting the new array via onChange — the input's own draft
        // text is untouched by removing a chip.
        <span
          key={`${value}-${index}`}
          onMouseDown={(e) => e.preventDefault()}
          className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-medium text-accent"
        >
          {value}
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={(e) => {
              e.stopPropagation();
              onChange(values.filter((_, i) => i !== index));
            }}
            aria-label={`Remove ${value}`}
            className="rounded-full hover:bg-accent/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => commit(draft)}
        placeholder={values.length === 0 ? placeholder : ""}
        aria-label={rest["aria-label"] ?? placeholder}
        className="flex-1 min-w-[120px] bg-transparent text-sm outline-none placeholder:text-muted-foreground"
      />
    </div>
  );
}
