"use client";

import { motion } from "framer-motion";
import { PromptBox } from "@/components/dashboard/PromptBox";
import { CurriculumGrid } from "@/components/dashboard/CurriculumGrid";
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
 */
export default function DashboardPage() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0] ?? "there";

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
        </div>
        <CurriculumGrid />
      </motion.div>
    </div>
  );
}
