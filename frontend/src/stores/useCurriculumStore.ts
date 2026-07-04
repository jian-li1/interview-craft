import { create } from "zustand";
import type { CurriculumFull } from "@/lib/types";
import { curriculaApi } from "@/lib/api";

interface CurriculumState {
  curriculum: CurriculumFull | null;
  loading: boolean;
  error: string | null;
  lastUpdatedScope: { scope: string; moduleId?: string; sectionId?: string } | null;
  fetchCurriculum: (id: string) => Promise<void>;
  refetch: (scope?: { scope: string; moduleId?: string; sectionId?: string }) => Promise<void>;
  reset: () => void;
}

export const useCurriculumStore = create<CurriculumState>((set, get) => ({
  curriculum: null,
  loading: false,
  error: null,
  lastUpdatedScope: null,

  fetchCurriculum: async (id: string) => {
    set({ loading: true, error: null });
    try {
      const curriculum = await curriculaApi.get(id);
      set({ curriculum, loading: false });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to load curriculum", loading: false });
    }
  },

  refetch: async (scope) => {
    const current = get().curriculum;
    if (!current) return;
    try {
      const curriculum = await curriculaApi.get(current.id);
      set({ curriculum, lastUpdatedScope: scope ?? null });
    } catch {
      // Keep stale data on transient refetch failure; surfaced via toast elsewhere.
    }
  },

  reset: () => set({ curriculum: null, loading: false, error: null, lastUpdatedScope: null }),
}));
