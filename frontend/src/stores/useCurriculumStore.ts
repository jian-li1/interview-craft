import { create } from "zustand";
import type { CurriculumFull } from "@/lib/types";
import { curriculaApi } from "@/lib/api";

interface CurriculumState {
  curriculum: CurriculumFull | null;
  currentId: string | null;
  loading: boolean;
  error: string | null;
  lastUpdatedScope: { scope: string; moduleId?: string; sectionId?: string } | null;
  fetchCurriculum: (id: string) => Promise<void>;
  refetch: (scope?: { scope: string; moduleId?: string; sectionId?: string }) => Promise<void>;
  reset: () => void;
}

export const useCurriculumStore = create<CurriculumState>((set, get) => ({
  curriculum: null,
  currentId: null,
  loading: false,
  error: null,
  lastUpdatedScope: null,

  fetchCurriculum: async (id: string) => {
    // Set currentId synchronously so out-of-order responses (and refetch,
    // which reads currentId) always know which curriculum is "current."
    // Clear stale curriculum immediately when switching ids so the previous
    // curriculum never renders while the new one loads.
    const switchingCurriculum = get().currentId !== id;
    set({
      currentId: id,
      loading: true,
      error: null,
      ...(switchingCurriculum ? { curriculum: null, lastUpdatedScope: null } : {}),
    });
    try {
      const curriculum = await curriculaApi.get(id);
      if (get().currentId !== id) return; // a newer fetch superseded this one
      set({ curriculum, loading: false });
    } catch (err) {
      if (get().currentId !== id) return;
      set({ error: err instanceof Error ? err.message : "Failed to load curriculum", loading: false });
    }
  },

  refetch: async (scope) => {
    const id = get().currentId;
    if (!id) return;
    try {
      const curriculum = await curriculaApi.get(id);
      if (get().currentId !== id) return;
      set({ curriculum, lastUpdatedScope: scope ?? null });
    } catch {
      // Keep stale data on transient refetch failure; surfaced via toast elsewhere.
    }
  },

  reset: () =>
    set({ curriculum: null, currentId: null, loading: false, error: null, lastUpdatedScope: null }),
}));
