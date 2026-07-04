import { create } from "zustand";
import type { UserOut } from "@/lib/types";
import { authApi, ApiError } from "@/lib/api";

interface AuthState {
  user: UserOut | null;
  loading: boolean;
  initialized: boolean;
  fetchMe: () => Promise<void>;
  setUser: (user: UserOut | null) => void;
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
      set({ user: null });
    }
  },
}));
