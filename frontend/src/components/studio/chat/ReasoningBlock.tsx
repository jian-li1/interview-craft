"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BrainCircuit, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface ReasoningBlockProps {
  reasoning: string;
  streaming: boolean;
}

export function ReasoningBlock({ reasoning, streaming }: ReasoningBlockProps) {
  const [open, setOpen] = useState(streaming);

  if (!reasoning) return null;

  return (
    <div className="rounded-lg border border-border/70 bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        <BrainCircuit className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className={cn(streaming && "shimmer-text")}>
          {streaming ? "Thinking…" : "Thought process"}
        </span>
        <ChevronDown
          className={cn("ml-auto h-3.5 w-3.5 transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <p className="whitespace-pre-wrap px-3 pb-3 text-xs leading-relaxed text-muted-foreground">
              {reasoning}
              {streaming && <span className="blinking-caret" aria-hidden="true" />}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
