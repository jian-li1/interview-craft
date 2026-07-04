"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowUp, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/Input";
import { conversationsApi, ApiError } from "@/lib/api";

const EXAMPLE_PROMPTS = [
  "Staff Backend Engineer at a fintech startup",
  "Frontend interview at a FAANG company",
  "Data Science role, focus on SQL & stats",
  "System design interview for senior SWE",
  "Behavioral interview using the STAR method",
];

/**
 * The dashboard's "start a new curriculum" input: a textarea plus a row of
 * clickable example prompts. On submit (Enter without Shift, the send
 * button, or clicking an example) it calls `conversationsApi.create` with
 * the trimmed prompt, best-effort stashes the prompt in `sessionStorage`
 * (keyed by the new conversation id) so the studio can auto-send it as the
 * first message once mounted, then navigates to `/studio/{conversation_id}`.
 * Failure surfaces as a toast and re-enables the input.
 */
export function PromptBox() {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();

  async function submit(prompt: string) {
    const trimmed = prompt.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    try {
      const { conversation_id } = await conversationsApi.create({
        curriculum_prompt: trimmed,
      });
      try {
        sessionStorage.setItem(`ic:pending-prompt:${conversation_id}`, trimmed);
      } catch {
        // sessionStorage unavailable (private mode, etc.) — the agent just
        // won't auto-start and the user can resend from the composer.
      }
      router.push(`/studio/${conversation_id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't start your curriculum");
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-6">
      <label htmlFor="curriculum-prompt" className="text-sm font-medium">
        What interview are you preparing for?
      </label>
      <div className="mt-3 flex items-end gap-2 rounded-xl border border-input bg-background p-2 focus-within:ring-2 focus-within:ring-ring">
        <Textarea
          id="curriculum-prompt"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(value);
            }
          }}
          rows={2}
          placeholder="e.g. Senior Backend Engineer interview at a Series B fintech, focused on system design and Python"
          className="border-0 shadow-none focus-visible:ring-0 bg-transparent"
        />
        <motion.button
          whileTap={{ scale: 0.92 }}
          type="button"
          onClick={() => submit(value)}
          disabled={!value.trim() || submitting}
          aria-label="Start curriculum"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm transition-opacity disabled:opacity-40"
        >
          {submitting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <ArrowUp className="h-4 w-4" aria-hidden="true" />
          )}
        </motion.button>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {EXAMPLE_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => submit(prompt)}
            disabled={submitting}
            className="rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-accent/40 hover:text-foreground disabled:opacity-50"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
