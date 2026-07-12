"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowUp, Bot, Globe, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/Input";
import { ChipSelect, SEARCH_PROVIDER_LABELS } from "@/components/ui/ChipSelect";
import { conversationsApi, modelsApi, ApiError } from "@/lib/api";
import type { ModelOption } from "@/lib/types";

const EXAMPLE_PROMPTS = [
  "Staff Backend Engineer at a fintech startup",
  "Frontend interview at a FAANG company",
  "Data Science role, focus on SQL & stats",
  "System design interview for senior SWE",
  "Behavioral interview using the STAR method",
];

/**
 * The dashboard's "start a new curriculum" input: a textarea, a chip row
 * (model + search-provider selection, fetched once via `modelsApi.get` since
 * there's no WS connection yet at this point — the studio composer instead
 * hydrates its chips from `session_ready`), and a row of clickable example
 * prompts. On submit (Enter without Shift, the send button, or clicking an
 * example) it calls `conversationsApi.create` with the trimmed prompt plus
 * any chip selection, best-effort stashes the prompt in `sessionStorage`
 * (keyed by the new conversation id) so the studio can auto-send it as the
 * first message once mounted, then navigates to `/studio/{conversation_id}`.
 * Failure surfaces as a toast and re-enables the input.
 */
export function PromptBox() {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();

  // Chip options, fetched once on mount; left empty on failure so the chips simply
  // don't render (see the `.length > 0` guards below) rather than blocking the box.
  const [models, setModels] = useState<ModelOption[]>([]);
  const [searchProviders, setSearchProviders] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [selectedSearchProvider, setSelectedSearchProvider] = useState<string | null>(null);

  useEffect(() => {
    // `cancelled` guards against setting state after unmount (StrictMode double-fire /
    // navigating away mid-request), mirroring ProfileTab's fetch-on-mount pattern.
    let cancelled = false;
    modelsApi
      .get()
      .then((res) => {
        if (cancelled) return;
        setModels(res.models);
        setSearchProviders(res.search_providers);
        setSelectedModel(res.default_model);
        setSelectedSearchProvider(res.default_search_provider);
      })
      .catch(() => {
        // Options stay empty — the prompt box itself must never be blocked by this.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(prompt: string) {
    const trimmed = prompt.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    try {
      const { conversation_id } = await conversationsApi.create({
        curriculum_prompt: trimmed,
        // Only sent once a selection exists (post-fetch); omitted otherwise so the
        // backend leaves the conversation doc's fields null (server defaults apply).
        ...(selectedModel ? { selected_model: selectedModel } : {}),
        ...(selectedSearchProvider ? { search_provider: selectedSearchProvider } : {}),
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
      {/* Column layout: textarea on top (full width), chip row + submit button below —
          matches the studio composer's shape now that this box also offers chips. */}
      <div className="mt-3 flex flex-col gap-1 rounded-xl border border-input bg-background p-2 focus-within:ring-2 focus-within:ring-ring">
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
        <div className="flex flex-wrap items-center gap-1.5 px-1 pb-0.5">
          {models.length > 0 && (
            <ChipSelect
              icon={Bot}
              ariaLabel="Select model"
              value={selectedModel}
              onChange={setSelectedModel}
              disabled={submitting}
              options={models.map((m) => ({ id: m.id, label: m.id, badge: m.provider }))}
            />
          )}
          {searchProviders.length > 0 && (
            <ChipSelect
              icon={Globe}
              ariaLabel="Select search provider"
              value={selectedSearchProvider}
              onChange={setSelectedSearchProvider}
              disabled={submitting}
              options={searchProviders.map((p) => ({ id: p, label: SEARCH_PROVIDER_LABELS[p] ?? p }))}
            />
          )}
          <div className="flex-1" />
          <motion.button
            whileTap={{ scale: 0.92 }}
            type="button"
            onClick={() => submit(value)}
            disabled={!value.trim() || submitting}
            aria-label="Start curriculum"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm transition-opacity disabled:opacity-40"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <ArrowUp className="h-4 w-4" aria-hidden="true" />
            )}
          </motion.button>
        </div>
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
