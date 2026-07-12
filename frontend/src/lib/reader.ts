/**
 * Shared curriculum-flattening helpers used by both `ReaderView` (renders the flattened
 * traversal order) and the composer's "current section" chip (`ChatPanel`, which needs to
 * agree on exactly which section is displayed without importing anything from ReaderView —
 * that component sits behind the `ssr:false` boundary in `CurriculumPanel.tsx` and must
 * never be statically imported elsewhere, per frontend/CLAUDE.md's ssr:false rule). This
 * module is pure (no DOM/browser APIs) so it's safe to import from anywhere.
 */
import type { ActiveSelection } from "@/stores/useCurriculumStore";
import type { CurriculumFull, ModuleOut, SectionOut } from "@/lib/types";

/**
 * One row in the flattened module/section traversal order. `section` is null for a
 * module that has no sections yet (still being planned) — that case is represented as
 * its own single flat entry so it's still selectable/navigable.
 */
export interface FlatEntry {
  module: ModuleOut;
  section: SectionOut | null;
}

/**
 * Flattens a curriculum's modules/sections into a single ordered list: modules sorted by
 * `order`, each contributing either one entry per section (sorted by `order`) or, if it
 * has no sections yet, a single `section: null` entry. Exact logic moved from ReaderView's
 * former local `flat` useMemo — keep both consumers in sync by editing only here.
 */
export function flattenCurriculum(curriculum: CurriculumFull): FlatEntry[] {
  const modules = [...curriculum.modules].sort((a, b) => a.order - b.order);
  const entries: FlatEntry[] = [];
  for (const mod of modules) {
    const sections = [...mod.sections].sort((a, b) => a.order - b.order);
    if (sections.length === 0) {
      entries.push({ module: mod, section: null });
    } else {
      for (const sec of sections) entries.push({ module: mod, section: sec });
    }
  }
  return entries;
}

/**
 * Resolves an `ActiveSelection` to an index into `flat`, falling back gracefully when the
 * selection is null, or points at a module/section that no longer exists (e.g. after a
 * refetch) — default to the very first entry. Exact logic moved from ReaderView's former
 * local `activeIndex` useMemo.
 */
export function resolveActiveIndex(flat: FlatEntry[], activeSelection: ActiveSelection | null): number {
  if (activeSelection) {
    const idx = flat.findIndex((e) => {
      if (e.module.id !== activeSelection.moduleId) return false;
      if (activeSelection.sectionId == null) return e.section == null;
      return e.section?.id === activeSelection.sectionId;
    });
    if (idx !== -1) return idx;
    // Selection's module still exists but the exact section vanished — land on that
    // module's first entry instead of jumping away entirely.
    const modIdx = flat.findIndex((e) => e.module.id === activeSelection.moduleId);
    if (modIdx !== -1) return modIdx;
  }
  return 0;
}
