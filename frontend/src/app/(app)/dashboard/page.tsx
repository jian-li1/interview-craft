"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowDown, ArrowUp } from "lucide-react";
import { PromptBox } from "@/components/dashboard/PromptBox";
import { CurriculumGrid } from "@/components/dashboard/CurriculumGrid";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { useAuth } from "@/components/auth/AuthProvider";

// Time-of-day greeting shown in the page header; purely presentational and
// re-evaluated on every render (no memoization needed for a per-hour value).
function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * `/dashboard` — landing page for signed-in, onboarded users (rendered
 * inside the `(app)` route group's authenticated shell, so auth/onboarding
 * are already guaranteed by the parent layout).
 *
 * Renders three sections in order: a personalized greeting (reads the
 * current user from `useAuth`, the `AuthProvider` context — no fetch here),
 * `PromptBox` (the entry point for starting a new curriculum from a free-text
 * prompt), and `CurriculumGrid` (the list of the user's existing curricula).
 *
 * Data-fetching pattern: this page itself fetches nothing — it delegates to
 * `PromptBox` and `CurriculumGrid`, which each own their own REST calls via
 * `lib/api.ts` (e.g. `curriculaApi.list()`) inside their own `useEffect`.
 * Framer Motion is used purely for a staggered fade/slide-in entrance on
 * each section (`delay` increasing per block), no data implications.
 *
 * Owns two pieces of view-only local state passed down to `CurriculumGrid`:
 * `filter` (All curricula / Favorites, a `Tabs` segmented control) and
 * `sortDesc` (Updated-time sort direction, a small ghost toggle button).
 * Neither is persisted — both reset to their defaults on navigation/reload.
 */
export default function DashboardPage() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0] ?? "there";
  // All curricula vs. favorites-only filter for the grid below.
  const [filter, setFilter] = useState<"all" | "favorites">("all");
  // true = most recently updated first (default); false = least recent first.
  const [sortDesc, setSortDesc] = useState(true);

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:py-14">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <h1 className="text-2xl font-semibold sm:text-3xl">
          {greeting()}, {firstName}
        </h1>
        <p className="mt-1.5 text-muted-foreground">
          Ready to prep for your next interview?
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.05 }}
        className="mt-8"
      >
        <PromptBox />
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
        className="mt-10"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Your curricula</h2>
          <div className="flex items-center gap-2">
            {/* Sort toggle: flips updated_at direction; icon mirrors current order. */}
            <button
              type="button"
              onClick={() => setSortDesc((d) => !d)}
              aria-label={sortDesc ? "Sorted most recently updated first" : "Sorted least recently updated first"}
              className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground sm:text-sm"
            >
              Updated
              {sortDesc ? (
                <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
              ) : (
                <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
              )}
            </button>
            {/* All/Favorites segmented control, reusing the shared Tabs primitive. */}
            <Tabs value={filter} onValueChange={(v) => setFilter(v as "all" | "favorites")}>
              <TabsList aria-label="Curriculum filter">
                <TabsTrigger value="all">All curricula</TabsTrigger>
                <TabsTrigger value="favorites">Favorites</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </div>
        <CurriculumGrid filter={filter} sortDesc={sortDesc} />
      </motion.div>
    </div>
  );
}
