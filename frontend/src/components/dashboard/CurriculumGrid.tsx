"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { BookX, Star } from "lucide-react";
import { toast } from "sonner";
import { CurriculumCard } from "@/components/dashboard/CurriculumCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { curriculaApi, ApiError } from "@/lib/api";
import { DashboardSocket } from "@/lib/ws";
import type { CurriculumSummary } from "@/lib/types";

interface CurriculumGridProps {
  /** "favorites" narrows the rendered list to `c.favorite === true`. */
  filter: "all" | "favorites";
  /** Sort direction on `updated_at`: true = most recent first, false = least recent first. */
  sortDesc: boolean;
}

/**
 * Loads and renders the signed-in user's curricula as a responsive grid of
 * `CurriculumCard`s. Handles three non-happy-path states: a skeleton grid
 * while the initial `curriculaApi.list()` call is in flight, an
 * `EmptyState` if the call fails (and no cached data exists yet) or if the
 * list is empty. Live updates are push-based: a `DashboardSocket`
 * (`/ws/dashboard`) delivers `curriculum_updated`/`curriculum_deleted` events
 * as curricula change server-side (researching/planning/writing/reviewing
 * progress, status transitions, deletions) — no more 8s polling. On
 * reconnect after a dropped connection, the full list is refetched once to
 * catch anything missed while offline; deletions are also applied
 * optimistically via the `onDeleted` callback passed to each card.
 *
 * `filter`/`sortDesc` (owned by the parent dashboard page) are applied at
 * render time to a copy of the fetched list — the underlying `curricula`
 * state always keeps the server's original order, so filtering/sorting never
 * fights the WS upsert logic above. Favoriting is optimistic: `curriculaApi.update`
 * is fired immediately with the flipped flag and reverted on error; the
 * dashboard WS will also echo a `curriculum_updated` event back, which is a
 * harmless no-op replace at that point.
 */
export function CurriculumGrid({ filter, sortDesc }: CurriculumGridProps) {
  const [curricula, setCurricula] = useState<CurriculumSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Tracks whether the socket has ever dropped, so the first "open" after a
  // drop (not the very first connect) triggers a catch-up refetch.
  const hasDroppedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

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

    // Open the push-based dashboard socket in the same effect; closed in cleanup.
    const socket = new DashboardSocket();
    const offEvent = socket.onEvent((event) => {
      if (event.type === "curriculum_updated") {
        setCurricula((prev) => {
          if (!prev) return [event.curriculum];
          const idx = prev.findIndex((c) => c.id === event.curriculum.id);
          if (idx === -1) {
            // New curriculum: prepend (server orders by updated_at desc, so a
            // freshly-changed one belongs at the front).
            return [event.curriculum, ...prev];
          }
          // Existing card: replace in place, preserving grid position/order.
          const next = [...prev];
          next[idx] = event.curriculum;
          return next;
        });
      } else if (event.type === "curriculum_deleted") {
        setCurricula((prev) => prev?.filter((c) => c.id !== event.curriculum_id) ?? null);
      }
    });
    const offState = socket.onStateChange((state) => {
      if (state === "reconnecting") {
        hasDroppedRef.current = true;
      } else if (state === "open" && hasDroppedRef.current) {
        // Reconnected after a drop: refetch once to catch anything missed while offline.
        hasDroppedRef.current = false;
        void load();
      }
    });
    socket.connect();

    return () => {
      cancelled = true;
      offEvent();
      offState();
      socket.close();
    };
  }, []);

  // Optimistic favorite toggle: flip locally first, persist via PATCH, revert on error.
  // Derived from `curricula` (not a ref) so it always reads/writes the latest state.
  async function handleToggleFavorite(id: string, favorite: boolean) {
    const previous = curricula;
    setCurricula((prev) => prev?.map((c) => (c.id === id ? { ...c, favorite } : c)) ?? null);
    try {
      await curriculaApi.update(id, { favorite });
    } catch (err) {
      setCurricula(previous ?? null); // revert on failure
      toast.error(err instanceof ApiError ? err.message : "Failed to update favorite");
    }
  }

  // Apply filter/sort to a COPY at render time — `curricula` state itself always keeps
  // server order so the WS upsert logic above never has to fight a client-side sort.
  const visible = useMemo(() => {
    if (!curricula) return null;
    const filtered = filter === "favorites" ? curricula.filter((c) => c.favorite) : curricula;
    return [...filtered].sort((a, b) => {
      const diff = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
      return sortDesc ? -diff : diff;
    });
  }, [curricula, filter, sortDesc]);

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

  // Curricula exist, but the favorites filter matched none of them.
  if (visible && visible.length === 0 && filter === "favorites") {
    return (
      <EmptyState
        icon={Star}
        title="No favorites yet"
        description="Click the star on a curriculum card to add it to your favorites."
      />
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <AnimatePresence initial={false}>
        {visible?.map((c) => (
          <CurriculumCard
            key={c.id}
            curriculum={c}
            onDeleted={(id) => setCurricula((prev) => prev?.filter((c) => c.id !== id) ?? null)}
            onToggleFavorite={handleToggleFavorite}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
