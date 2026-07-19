import { create } from "zustand";
import type { CurriculumFull } from "@/lib/types";
import { curriculaApi } from "@/lib/api";

/** Which (module, section) the Reader view currently has open — null section means the
 * module has no sections yet (still planned). Moved here (from CurriculumPanel.tsx) so
 * both the Reader and the composer's "current section" chip (ChatPanel) can read it. */
export interface ActiveSelection {
  moduleId: string;
  sectionId: string | null;
}

/** Curriculum panel's top-level view toggle — Workflow (React Flow canvas) or Reader
 * (single-section paging view). Lives here (not local component state) so the composer's
 * section-context chip can read it without prop-drilling through CurriculumPanel. */
export type CurriculumView = "workflow" | "reader";

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
  /** Whether the curriculum panel is in full-screen focus mode (hides app chrome + chat; see AppShell/StudioPage/CurriculumPanel). */
  focusMode: boolean;
  /**
   * Last user-set pan/zoom of the Workflow canvas, saved on move-end so the
   * camera survives Workflow<->Reader switches (WorkflowView unmounts on
   * switch). null = never moved yet, let fitView run. Shape mirrors React
   * Flow's Viewport but is defined inline — this store stays free of any
   * @xyflow/react coupling.
   */
  workflowViewport: { x: number; y: number; zoom: number } | null;
  /** Curriculum panel's Workflow/Reader toggle; see `CurriculumView` doc comment above. Lifted from CurriculumPanel local state so ChatPanel's section-context chip can read it too. */
  view: CurriculumView;
  /** The Reader's current (module, section) selection; see `ActiveSelection` doc comment above. Lifted from CurriculumPanel local state for the same reason as `view`. */
  activeSelection: ActiveSelection | null;
  /** Loads a curriculum by id from scratch, clearing any previously-loaded curriculum first if the id is changing (see in-line comment below). */
  fetchCurriculum: (id: string) => Promise<void>;
  /**
   * Re-fetches the currently-tracked curriculum (no-ops if none is set).
   * Called from `useChatSocket.ts` on `curriculum_updated` WS events, passing
   * through the event's `scope`/`module_id`/`section_id` as `lastUpdatedScope`.
   */
  refetch: (scope?: { scope: string; moduleId?: string; sectionId?: string }) => Promise<void>;
  /** Toggles full-screen focus mode; see `focusMode` doc comment above. */
  setFocusMode: (on: boolean) => void;
  /** Saves the Workflow canvas's pan/zoom; see `workflowViewport` doc comment above. */
  setWorkflowViewport: (viewport: { x: number; y: number; zoom: number }) => void;
  /** Switches the curriculum panel's Workflow/Reader view. */
  setView: (view: CurriculumView) => void;
  /** Updates the Reader's active (module, section) selection. */
  setActiveSelection: (selection: ActiveSelection | null) => void;
  /** Applies a rename (title/description) from the RenameCurriculumDialog's PATCH
   * response without a full refetch; no-ops if no curriculum is currently loaded. */
  applyMeta: (fields: { title?: string; description?: string }) => void;
  reset: () => void;
}

export const useCurriculumStore = create<CurriculumState>((set, get) => ({
  curriculum: null,
  currentId: null,
  loading: false,
  error: null,
  lastUpdatedScope: null,
  focusMode: false,
  workflowViewport: null,
  view: "workflow",
  activeSelection: null,

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
      // A saved camera (and reader position) from one curriculum makes no sense on
      // another, so clear view/selection back to the workflow default too.
      ...(switchingCurriculum
        ? { curriculum: null, lastUpdatedScope: null, workflowViewport: null, view: "workflow", activeSelection: null }
        : {}),
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

  // Simple setter: just flips the flag; consumers (AppShell/StudioPage/CurriculumPanel) react to it.
  setFocusMode: (on: boolean) => set({ focusMode: on }),

  // Simple setter: overwrites the saved camera; called from WorkflowView's onMoveEnd.
  setWorkflowViewport: (viewport) => set({ workflowViewport: viewport }),

  // Simple setter: switches the panel's Workflow/Reader tab (CurriculumPanel's Tabs).
  setView: (view) => set({ view }),

  // Simple setter: updates the Reader's active (module, section) pair.
  setActiveSelection: (selection) => set({ activeSelection: selection }),

  // Shallow-merges a rename into the loaded curriculum; no-op if none is loaded.
  applyMeta: (fields) => {
    const current = get().curriculum;
    if (!current) return;
    set({ curriculum: { ...current, ...fields } });
  },

  reset: () =>
    set({
      curriculum: null,
      currentId: null,
      loading: false,
      error: null,
      lastUpdatedScope: null,
      focusMode: false,
      workflowViewport: null,
      view: "workflow",
      activeSelection: null,
    }),
}));
