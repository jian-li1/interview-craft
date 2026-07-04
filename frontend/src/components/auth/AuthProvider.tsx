"use client";

import { createContext, useContext, useEffect, useRef } from "react";
import { useAuthStore } from "@/stores/useAuthStore";
import type { UserOut } from "@/lib/types";

interface AuthContextValue {
  user: UserOut | null;
  loading: boolean;
  initialized: boolean;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Fetches /api/auth/me once on mount and exposes the current user globally.
 * Individual route groups layer on redirect behavior via `useAuthGuard`.
 *
 * This is a thin context wrapper around `useAuthStore`: the store itself
 * holds the session state (`user`/`loading`/`initialized`), while this
 * component's only job is to kick off the one-time `fetchMe()` call and
 * republish the store's fields through React context so consumers can read
 * them via `useAuth()` instead of subscribing to the store directly.
 *
 * Contract for consumers: `AuthProvider` must be mounted above any component
 * that calls `useAuth()` (directly or transitively via `useAuthGuard`) —
 * e.g. it should wrap the root layout — otherwise `useAuth()` throws.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);
  const initialized = useAuthStore((s) => s.initialized);
  const fetchMe = useAuthStore((s) => s.fetchMe);
  // Guards against React 18 Strict Mode's double-invoked effects (and any
  // re-render before the fetch settles) firing /api/auth/me more than once.
  const hasFetched = useRef(false);

  useEffect(() => {
    if (hasFetched.current) return;
    hasFetched.current = true;
    void fetchMe();
  }, [fetchMe]);

  return (
    <AuthContext.Provider value={{ user, loading, initialized, refresh: fetchMe }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Reads the current session (`user`, `loading`, `initialized`, `refresh`)
 * from the nearest `AuthProvider`. Throws if called outside one — see the
 * mounting contract documented on `AuthProvider` above.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
