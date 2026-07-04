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

  const ready = initialized && !loading;
  return { user, ready };
}
