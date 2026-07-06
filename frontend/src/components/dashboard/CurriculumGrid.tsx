"use client";

import { useEffect, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { BookX } from "lucide-react";
import { CurriculumCard } from "@/components/dashboard/CurriculumCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { curriculaApi, ApiError } from "@/lib/api";
import type { CurriculumSummary } from "@/lib/types";

/**
 * Loads and renders the signed-in user's curricula as a responsive grid of
 * `CurriculumCard`s. Handles three non-happy-path states: a skeleton grid
 * while the initial `curriculaApi.list()` call is in flight, an
 * `EmptyState` if the call fails (and no cached data exists yet) or if the
 * list is empty. While loaded, it polls `curriculaApi.list()` every 8s so
 * in-progress curricula (researching/planning/writing/reviewing) pick up status and
 * progress updates without a manual refresh; deletions are applied
 * optimistically via the `onDeleted` callback passed to each card.
 */
export function CurriculumGrid() {
  const [curricula, setCurricula] = useState<CurriculumSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;

    async function load() {
      try {
        const data = await curriculaApi.list();
        if (!cancelled) {
          setCurricula(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load curricula");
        }
      }
    }

    load();
    // Light polling so in-progress curricula update without a full refresh.
    interval = setInterval(load, 8000);

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, []);

  if (error && !curricula) {
    return (
      <EmptyState
        icon={BookX}
        title="Couldn't load your curricula"
        description={error}
      />
    );
  }

  if (!curricula) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-48 rounded-xl" />
        ))}
      </div>
    );
  }

  if (curricula.length === 0) {
    return (
      <EmptyState
        icon={BookX}
        title="No curricula yet"
        description="Describe an interview you're preparing for above to generate your first curriculum."
      />
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <AnimatePresence initial={false}>
        {curricula.map((c) => (
          <CurriculumCard
            key={c.id}
            curriculum={c}
            onDeleted={(id) => setCurricula((prev) => prev?.filter((c) => c.id !== id) ?? null)}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
