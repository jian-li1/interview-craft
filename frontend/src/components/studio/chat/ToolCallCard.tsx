"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ChevronDown, Loader2, Search, Wrench, XCircle } from "lucide-react";
import { cn, formatElapsed } from "@/lib/utils";
import type { ToolCallRecord } from "@/lib/types";

// Substring match against the tool's raw name (e.g. "web_search",
// "deep_search") -> icon. Falls back to a generic wrench for any tool name
// that doesn't match a known keyword.
const ICONS: Record<string, typeof Wrench> = {
  search: Search,
  web_search: Search,
};

function iconFor(name: string) {
  const key = name.toLowerCase();
  for (const [k, icon] of Object.entries(ICONS)) {
    if (key.includes(k)) return icon;
  }
  return Wrench;
}

/** Turns a snake_case tool name (e.g. "web_search") into a title-cased display label ("Web Search"). */
function humanizeName(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * One collapsible tool-call row. Populated from a `ToolCallRecord` that's
 * created by `tool_call_start` (-> useChatStore.startToolCall) and updated in
 * place by `tool_call_result` (-> resolveToolCall) — see useChatSocket.ts.
 *
 * Status indicator (right-aligned, before the chevron):
 *  - `"running"` — spinning loader; no elapsed time shown yet (the result
 *    hasn't arrived, so `elapsed_ms` is still undefined).
 *  - `"ok"` — green check, plus the elapsed time once available.
 *  - `"error"` — red X, plus the elapsed time once available.
 *
 * The disclosure (closed by default) reveals the raw JSON `input` the tool
 * was called with, and — if present — the tool's output: `output_full` (the
 * complete result, same text the model saw), falling back to the short
 * `output_preview` for legacy records that predate the full field. The pane
 * is scroll-capped so a large result stays contained.
 */
function ToolCallItem({ call }: { call: ToolCallRecord }) {
  const [open, setOpen] = useState(false);
  const Icon = iconFor(call.name);

  return (
    <div className="rounded-lg border border-border/70 bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs"
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="font-medium">{humanizeName(call.name)}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {call.elapsed_ms !== undefined && call.status !== "running" && (
            <span className="text-[10px] tabular-nums text-muted-foreground">
              {formatElapsed(call.elapsed_ms)}
            </span>
          )}
          {call.status === "running" && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-label="Running" />
          )}
          {call.status === "ok" && (
            <CheckCircle2 className="h-3.5 w-3.5 text-success" aria-label="Succeeded" />
          )}
          {call.status === "error" && (
            <XCircle className="h-3.5 w-3.5 text-destructive" aria-label="Failed" />
          )}
          <ChevronDown
            className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-180")}
            aria-hidden="true"
          />
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-t border-border/70"
          >
            <div className="space-y-2 p-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Input
                </p>
                <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-muted/60 p-2 text-[11px] leading-relaxed whitespace-pre-wrap scrollbar-thin">
                  {JSON.stringify(call.input, null, 2)}
                </pre>
              </div>
              {(call.output_full || call.output_preview) && (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Output
                  </p>
                  <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-muted/60 p-2 text-[11px] leading-relaxed whitespace-pre-wrap scrollbar-thin">
                    {call.output_full || call.output_preview}
                  </pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Renders a group of consecutive tool calls belonging to one assistant message. */
export function ToolCallGroup({ calls }: { calls: ToolCallRecord[] }) {
  if (calls.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {calls.map((call) => (
        <ToolCallItem key={call.id} call={call} />
      ))}
    </div>
  );
}
