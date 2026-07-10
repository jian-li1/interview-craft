"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { toast } from "sonner";
import { GoogleSignInButton } from "@/components/auth/GoogleSignInButton";
import { useAuthGuard } from "@/components/auth/useAuthGuard";
import { authApi, ApiError } from "@/lib/api";
import { useAuthStore } from "@/stores/useAuthStore";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

/**
 * `/login` — public sign-in page (Google Identity Services).
 *
 * Auth-guard interaction: calls `useAuthGuard({ redirectIfAuthed: true })`,
 * which immediately redirects an already-authenticated visitor away from
 * this page (to dashboard/onboarding per their state) instead of showing the
 * sign-in form again. `ready` stays false until that check resolves, so we
 * render a centered spinner in the meantime to avoid a flash of the login UI
 * for users who are about to be redirected.
 *
 * Sign-in flow: `GoogleSignInButton` renders Google's identity widget and
 * hands us a raw Google ID token via `onCredential`. `handleCredential`
 * exchanges that token for our own session by calling
 * `authApi.loginWithGoogle`, which sets the backend's httpOnly `ic_session`
 * JWT cookie and returns the user record. On success we hydrate
 * `useAuthStore` with that user, toast a welcome message, and redirect:
 * to `/dashboard` if `user.onboarding_completed`, otherwise to `/onboarding`
 * (new users must finish the profile wizard first). Failures surface as an
 * error toast and re-enable the button.
 */
export default function LoginPage() {
  const { ready } = useAuthGuard({ redirectIfAuthed: true });
  const setUser = useAuthStore((s) => s.setUser);
  const router = useRouter();
  const [signingIn, setSigningIn] = useState(false);

  // Callback passed to GoogleSignInButton; fires once Google returns a
  // signed ID token for the chosen account. Wrapped in useCallback so the
  // button (and any effect that reads this) doesn't see a new function
  // identity on every render.
  const handleCredential = useCallback(
    async (idToken: string) => {
      setSigningIn(true);
      try {
        // Exchange the Google ID token for our own backend session (sets
        // the httpOnly ic_session cookie server-side) and get the user back.
        const user = await authApi.loginWithGoogle(idToken);
        setUser(user);
        toast.success(`Welcome, ${user.name.split(" ")[0]}!`);
        // Route new users into the onboarding wizard; returning users go
        // straight to their dashboard.
        router.push(user.onboarding_completed ? "/dashboard" : "/onboarding");
      } catch (err) {
        const message =
          err instanceof ApiError ? err.message : "Sign-in failed. Please try again.";
        toast.error(message);
      } finally {
        setSigningIn(false);
      }
    },
    [setUser, router]
  );

  // Auth-guard check hasn't resolved yet (or is redirecting an already
  // signed-in user away) — show a spinner instead of the sign-in form.
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 flex justify-center blur-3xl"
      >
        <div className="h-72 w-[36rem] bg-gradient-accent opacity-20" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
        className="w-full max-w-sm rounded-2xl border border-border bg-card p-8 shadow-lg"
      >
        <div className="flex flex-col items-center text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-accent text-white">
            <Sparkles className="h-5 w-5" aria-hidden="true" />
          </span>
          <h1 className="mt-4 text-xl font-semibold">Welcome to InterviewBlueprint</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            Sign in to start building your interview curriculum.
          </p>
        </div>

        <div className="mt-8">
          <GoogleSignInButton onCredential={handleCredential} disabled={signingIn} />
        </div>

        {signingIn && (
          <p className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            Signing you in…
          </p>
        )}

        <p className="mt-8 text-center text-xs text-muted-foreground">
          By continuing, you agree to InterviewBlueprint&apos;s Terms and acknowledge our
          Privacy Policy.
        </p>
      </motion.div>

      <Link
        href="/"
        className="mt-6 text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
      >
        &larr; Back to home
      </Link>
    </div>
  );
}
