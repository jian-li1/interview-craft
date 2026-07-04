import { create } from "zustand";
import type { CurriculumFull } from "@/lib/types";
import { curriculaApi } from "@/lib/api";

/**
 * Concern boundary: ONE ACTIVE CURRICULUM.
 *
 * Holds the full nested modules/sections tree for whichever curriculum is
 * currently open in the studio (`CurriculumPanel`/`ReaderView`/`WorkflowView`),
 * plus load state. Distinct from `useChatStore`, which owns the conversation
 * that drives generation — this store only owns the resulting document.
 */
interface CurriculumState {
  /** The full curriculum document, or null if not yet loaded / reset. */
  curriculum: CurriculumFull | null;
  /** id of the curriculum this store is currently tracking; used to guard against out-of-order async responses (see `fetchCurriculum`/`refetch`). */
  currentId: string | null;
  loading: boolean;
  error: string | null;
  /**
   * The scope of the most recent `refetch` (mirrors `CurriculumUpdatedEvent`
   * from `curriculum_updated` WS events: "overview" | "module" | "section",
   * plus the affected module/section id). Consumers can use this to target
   * a narrower re-render or highlight (e.g. flash just the updated section)
   * instead of treating every refetch as a full-document replace. Currently
   * `refetch` always re-fetches the whole curriculum via `curriculaApi.get`
   * regardless of scope — the scope is metadata for the UI layer, not (yet)
   * used to make the fetch itself partial.
   */
  lastUpdatedScope: { scope: string; moduleId?: string; sectionId?: string } | null;
  /** Loads a curriculum by id from scratch, clearing any previously-loaded curriculum first if the id is changing (see in-line comment below). */
  fetchCurriculum: (id: string) => Promise<void>;
  /**
   * Re-fetches the currently-tracked curriculum (no-ops if none is set).
   * Called from `useChatSocket.ts` on `curriculum_updated` WS events, passing
   * through the event's `scope`/`module_id`/`section_id` as `lastUpdatedScope`.
   */
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
    // No-op if nothing is currently tracked (e.g. a curriculum_updated event
    // arrives for a conversation whose curriculum hasn't been opened yet).
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
