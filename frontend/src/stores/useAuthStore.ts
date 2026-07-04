import { create } from "zustand";
import type { UserOut } from "@/lib/types";
import { authApi, ApiError } from "@/lib/api";

/**
 * Concern boundary: SESSION. Holds the current authenticated user (if any)
 * and the loading/initialized flags `AuthProvider`/`useAuthGuard` use to
 * decide whether to show a loading state, render the app, or redirect to
 * `/login`. Does NOT hold anything about a specific conversation or
 * curriculum — see `useChatStore` and `useCurriculumStore` for those.
 */
interface AuthState {
  /** The logged-in user, or null if unauthenticated / not yet checked. */
  user: UserOut | null;
  /** True while `fetchMe` is in flight. */
  loading: boolean;
  /** True once the initial `fetchMe` call has resolved (success or failure) — lets consumers distinguish "still checking" from "checked, not logged in". */
  initialized: boolean;
  /** Calls `/api/auth/me` (with `skipAuthRedirect`, since a 401 here is an expected "not logged in" state, not a redirect trigger) and syncs `user`/`loading`/`initialized`. */
  fetchMe: () => Promise<void>;
  /** Directly sets the user, e.g. right after a successful Google sign-in response. */
  setUser: (user: UserOut | null) => void;
  /** Calls the backend logout endpoint, then clears `user` regardless of whether the request succeeded. */
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: true,
  initialized: false,

  fetchMe: async () => {
    set({ loading: true });
    try {
      const user = await authApi.me(true);
      set({ user, loading: false, initialized: true });
    } catch (err) {
      // Both branches currently behave identically (clear the user and mark
      // initialized) — the ApiError/401 check is kept distinct in case
      // future handling needs to differ for auth failures vs. other errors
      // (e.g. network errors surfacing a toast).
      if (err instanceof ApiError && err.status === 401) {
        set({ user: null, loading: false, initialized: true });
      } else {
        set({ user: null, loading: false, initialized: true });
      }
    }
  },

  setUser: (user) => set({ user }),

  logout: async () => {
    try {
      await authApi.logout();
    } finally {
      // Clear local state even if the network call failed, so the UI never
      // gets stuck showing a "logged in" state the server has already ended.
      set({ user: null });
    }
  },
}));
