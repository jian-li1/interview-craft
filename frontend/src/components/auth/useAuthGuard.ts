"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/AuthProvider";

interface GuardOptions {
  /** Redirect to /login if no user is present. */
  requireAuth?: boolean;
  /** Redirect to /onboarding if the user's profile isn't complete yet. */
  requireOnboarding?: boolean;
  /** Redirect to /dashboard if the user IS authenticated (for /login page). */
  redirectIfAuthed?: boolean;
}

/**
 * Client-side auth guard used by protected route layouts. Waits for the
 * initial /api/auth/me fetch to resolve before making redirect decisions.
 * `ready` also stays false while a redirect is in flight (see `redirecting`
 * below), so callers never render the wrong page for a few frames between
 * the effect firing and `router.replace` actually navigating away.
 */
export function useAuthGuard({
  requireAuth = false,
  requireOnboarding = false,
  redirectIfAuthed = false,
}: GuardOptions) {
  const { user, loading, initialized } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!initialized || loading) return;

    if (redirectIfAuthed && user) {
      router.replace(user.onboarding_completed ? "/dashboard" : "/onboarding");
      return;
    }

    if (requireAuth && !user) {
      router.replace("/login");
      return;
    }

    if (requireAuth && user && requireOnboarding && !user.onboarding_completed) {
      router.replace("/onboarding");
      return;
    }
  }, [initialized, loading, user, requireAuth, requireOnboarding, redirectIfAuthed, router]);

  // Mirrors the effect's own branch conditions so `ready` can go false the
  // instant a redirect is decided, not just once initialized+!loading are true.
  const redirecting =
    initialized &&
    !loading &&
    ((redirectIfAuthed && !!user) ||
      (requireAuth && !user) ||
      (requireAuth && !!user && requireOnboarding && !user.onboarding_completed));

  const ready = initialized && !loading && !redirecting;
  return { user, ready };
}
