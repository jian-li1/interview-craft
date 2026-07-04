"use client";

import { Loader2 } from "lucide-react";
import { useAuthGuard } from "@/components/auth/useAuthGuard";
import { AppShell } from "@/components/layout/AppShell";

/**
 * Layout for the `(app)` route group — the single gate protecting every
 * authenticated route (dashboard, settings, studio, etc.).
 *
 * Because Next.js route groups share one layout across all nested routes,
 * putting the guard HERE (rather than in each page) means any new page
 * added under `(app)/` automatically inherits auth + onboarding protection
 * for free, with no per-page boilerplate and no risk of a page forgetting
 * to check. This is why CLAUDE.md calls this out as "the single gate":
 * there is intentionally no other place in the authenticated tree that
 * re-checks auth.
 *
 * `useAuthGuard({ requireAuth: true, requireOnboarding: true })` redirects
 * unauthenticated visitors to `/login` and authenticated-but-not-yet-
 * onboarded users to `/onboarding`, so by the time `ready` is true here we
 * know the current user is signed in AND has completed the profile wizard.
 * Until then we render a centered spinner rather than `children`, so no
 * authenticated-only content/data fetch ever mounts before the guard clears.
 *
 * Once ready, `children` (the actual page) is rendered inside `AppShell`,
 * which supplies the persistent chrome (sidebar/nav) shared by every
 * authenticated page.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { ready } = useAuthGuard({ requireAuth: true, requireOnboarding: true });

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
