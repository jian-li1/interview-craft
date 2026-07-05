"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  List,
  Loader2,
} from "lucide-react";
import { SectionContent } from "@/components/studio/curriculum/SectionContent";
import { cn } from "@/lib/utils";
import type { CurriculumFull, ModuleOut, ModuleStatus, SectionOut, SectionStatus } from "@/lib/types";
import type { ActiveSelection } from "@/components/studio/curriculum/CurriculumPanel";

interface ReaderViewProps {
  curriculum: CurriculumFull;
  activeSelection: ActiveSelection | null;
  onSelectSection: (moduleId: string, sectionId: string | null) => void;
  onExplain: (prompt: string) => void;
}

// Shared status -> icon mapping for both modules and sections in the TOC
// (module/section status is written server-side as the agent writes each
// piece of content, and flows down through CurriculumFull -> ModuleOut/
// SectionOut; the panel refetches this via `curriculum_updated` WS events,
// see useChatSocket.ts).
const STATUS_ICON: Record<ModuleStatus | SectionStatus, typeof Circle> = {
  planned: Circle,
  writing: Loader2,
  complete: CheckCircle2,
};

/** Text color for a module/section's status icon and label in the TOC. */
function statusClasses(status: ModuleStatus | SectionStatus): string {
  if (status === "complete") return "text-success";
  if (status === "writing") return "text-accent";
  return "text-muted-foreground";
}

/**
 * One row in the flattened module/section traversal order (see `flat`
 * below). `section` is null for a module that has no sections yet (still
 * being planned) — that case is represented as its own single flat entry so
 * it's still selectable/navigable in the TOC and via Prev/Next.
 */
interface FlatEntry {
  module: ModuleOut;
  section: SectionOut | null;
}

/**
 * Reader view: a left mini-TOC (modules -> sections, with status icons) and a
 * single-section content pane. Selecting a TOC entry (or a Prev/Next button)
 * changes which section is shown — no scrolling within a long document.
 *
 * This is the "single-section reader paging" model (see recent commit
 * history): rather than rendering the whole curriculum as one long
 * scrollable document, exactly one (module, section) pair is "active" at a
 * time, driven by `activeSelection` (owned by the parent, CurriculumPanel,
 * as `ActiveSelection`) and changed only via `onSelectSection` — clicking a
 * TOC entry or a Prev/Next button. This keeps each page focused and lets the
 * content pane's scroll position reset per-section (see the effect below)
 * instead of accumulating one giant scroll position across the whole
 * curriculum.
 *
 * Rendered client-only via CurriculumPanel's `next/dynamic(..., { ssr: false
 * })` boundary, because this component's content tree (SectionContent ->
 * MermaidDiagram) renders Mermaid diagrams that require a browser DOM.
 */
export function ReaderView({
  curriculum,
  activeSelection,
  onSelectSection,
  onExplain,
}: ReaderViewProps) {
  const modules = useMemo(
    () => [...curriculum.modules].sort((a, b) => a.order - b.order),
    [curriculum.modules]
  );

  // Flattened module/section order used for prev/next traversal and for
  // resolving the active selection to a concrete (module, section) pair.
  const flat = useMemo<FlatEntry[]>(() => {
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
  }, [modules]);

  // `tocOpen` only matters for the compact (below-lg) dropdown TOC toggle;
  // the lg+ mini TOC in the sidebar is always visible and ignores this state.
  const [tocOpen, setTocOpen] = useState(false);
  const tocRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Close the compact TOC dropdown on any click outside of it. Only attaches
  // the listener while the dropdown is actually open, to avoid a global
  // mousedown listener sitting around for the entire lifetime of the reader.
  useEffect(() => {
    if (!tocOpen) return;
    function onClick(e: MouseEvent) {
      if (tocRef.current && !tocRef.current.contains(e.target as Node)) setTocOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [tocOpen]);

  // Resolve the active index within `flat`, falling back gracefully when the
  // selection is null, or points at a module/section that no longer exists
  // (e.g. after a refetch) — default to the very first entry.
  const activeIndex = useMemo(() => {
    if (activeSelection) {
      const idx = flat.findIndex((e) => {
        if (e.module.id !== activeSelection.moduleId) return false;
        if (activeSelection.sectionId == null) return e.section == null;
        return e.section?.id === activeSelection.sectionId;
      });
      if (idx !== -1) return idx;
      // Selection's module still exists but the exact section vanished —
      // land on that module's first entry instead of jumping away entirely.
      const modIdx = flat.findIndex((e) => e.module.id === activeSelection.moduleId);
      if (modIdx !== -1) return modIdx;
    }
    return 0;
  }, [activeSelection, flat]);

  const current = flat[activeIndex] ?? null;

  // Reset content scroll position to top whenever the active section changes.
  // This is the paging behavior's scroll reset: since each (module, section)
  // is presented as its own "page" rather than an anchor within one long
  // document, switching pages should always start the reader at the top of
  // the new page rather than preserving the previous page's scroll offset.
  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0 });
  }, [current?.module.id, current?.section?.id]);

  // Central navigation function used by every TOC entry, and by Prev/Next —
  // notifies the parent (which owns `activeSelection` and re-renders us with
  // the new value) and closes the compact dropdown TOC if it was open.
  function select(moduleId: string, sectionId: string | null) {
    onSelectSection(moduleId, sectionId);
    setTocOpen(false);
  }

  if (modules.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-muted-foreground">
        No modules yet — the outline will populate here once the agent starts writing.
      </div>
    );
  }

  // Prev/Next entries in the flattened traversal order, used both to render
  // the bottom navigation buttons (disabled at the very start/end) and to
  // drive `select()` when they're clicked.
  const prevEntry = activeIndex > 0 ? flat[activeIndex - 1] : null;
  const nextEntry = activeIndex < flat.length - 1 ? flat[activeIndex + 1] : null;

  // Shared TOC markup, rendered twice below: once inside the collapsible
  // dropdown for narrow (<lg) viewports, once inline in the always-visible
  // sidebar for lg+ viewports. Kept as a single JSX value so both renders
  // stay in sync.
  const tocList = (
    <ul className="space-y-3">
      {modules.map((mod) => {
        const ModIcon = STATUS_ICON[mod.status];
        const isActiveModule = current?.module.id === mod.id;
        return (
          <li key={mod.id}>
            <button
              type="button"
              onClick={() => select(mod.id, [...mod.sections].sort((a, b) => a.order - b.order)[0]?.id ?? null)}
              className={cn(
                "flex w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-left text-xs font-semibold hover:bg-muted",
                isActiveModule && mod.sections.length === 0 && "text-accent"
              )}
            >
              <ModIcon
                className={cn("h-3.5 w-3.5 shrink-0", statusClasses(mod.status), mod.status === "writing" && "animate-spin")}
                aria-hidden="true"
              />
              <span className="truncate">
                {/* order is 0-based in Firestore; display 1-based */}
                {mod.order + 1}. {mod.title}
              </span>
            </button>
            {mod.sections.length > 0 && (
              <ul className="mt-1.5 space-y-1 border-l border-border pl-4">
                {[...mod.sections]
                  .sort((a, b) => a.order - b.order)
                  .map((sec) => {
                    const SecIcon = STATUS_ICON[sec.status];
                    const isActive = current?.section?.id === sec.id;
                    return (
                      <li key={sec.id}>
                        <button
                          type="button"
                          onClick={() => select(mod.id, sec.id)}
                          className={cn(
                            "flex w-full items-center gap-1.5 truncate rounded-md px-1.5 py-1 text-left text-xs text-muted-foreground hover:bg-muted hover:text-foreground",
                            isActive && "bg-accent-soft text-accent"
                          )}
                        >
                          <SecIcon
                            className={cn("h-3 w-3 shrink-0", statusClasses(sec.status), sec.status === "writing" && "animate-spin")}
                            aria-hidden="true"
                          />
                          <span className="truncate">{sec.title}</span>
                        </button>
                      </li>
                    );
                  })}
              </ul>
            )}
          </li>
        );
      })}
    </ul>
  );

  const currentModule = current?.module ?? null;
  const currentSection = current?.section ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col lg:flex-row">
      {/* Compact TOC toggle (below lg) */}
      <div ref={tocRef} className="relative shrink-0 border-b border-border lg:hidden">
        <button
          type="button"
          onClick={() => setTocOpen((o) => !o)}
          aria-haspopup="true"
          aria-expanded={tocOpen}
          aria-label="Table of contents"
          className="flex w-full items-center gap-2 px-4 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        >
          <List className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium">
            {/* order is 0-based in Firestore; display 1-based */}
            {currentModule ? `${currentModule.order + 1}. ${currentModule.title}` : "Contents"}
          </span>
          <ChevronDown
            className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", tocOpen && "rotate-180")}
            aria-hidden="true"
          />
        </button>
        <AnimatePresence>
          {tocOpen && (
            <motion.nav
              aria-label="Table of contents"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.15 }}
              className="absolute inset-x-0 top-full z-20 max-h-[60vh] overflow-y-auto border-b border-border bg-popover p-3 shadow-lg scrollbar-thin"
            >
              {tocList}
            </motion.nav>
          )}
        </AnimatePresence>
      </div>

      {/* Mini TOC (lg+) */}
      <nav
        aria-label="Table of contents"
        className="hidden w-56 shrink-0 overflow-y-auto border-r border-border p-3 scrollbar-thin lg:block"
      >
        {tocList}
      </nav>

      {/* Content: one section at a time */}
      <div ref={contentRef} className="min-w-0 flex-1 overflow-y-auto p-6 scrollbar-thin">
        <AnimatePresence mode="wait" initial={false}>
          {currentModule && (
            <motion.div
              key={`${currentModule.id}-${currentSection?.id ?? "empty"}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
            >
              <div className="mb-4 flex items-start justify-between gap-3 border-b border-border pb-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-accent">
                    {/* order is 0-based in Firestore; display 1-based */}
                    Module {currentModule.order + 1}
                  </p>
                  <h2 className="text-xl font-semibold">{currentModule.title}</h2>
                  {currentModule.summary && (
                    <p className="mt-1 text-sm text-muted-foreground">{currentModule.summary}</p>
                  )}
                </div>
              </div>

              {!currentSection ? (
                <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  {currentModule.status === "planned"
                    ? "This module hasn't been written yet."
                    : "Writing in progress…"}
                </div>
              ) : (
                <div className="mb-2">
                  <h3 className="mb-2 flex items-center gap-2 text-base font-semibold">
                    {currentSection.title}
                  </h3>
                  {currentSection.status === "planned" ? (
                    <p className="text-sm text-muted-foreground">Not written yet.</p>
                  ) : (
                    <SectionContent section={currentSection} onExplain={onExplain} />
                  )}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Prev / Next section navigation */}
        <div className="mt-8 flex items-center justify-between gap-3 border-t border-border pt-4">
          <button
            type="button"
            disabled={!prevEntry}
            onClick={() => prevEntry && select(prevEntry.module.id, prevEntry.section?.id ?? null)}
            className={cn(
              "flex min-w-0 max-w-[45%] items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-left text-xs font-medium transition-colors",
              prevEntry
                ? "text-foreground hover:bg-muted"
                : "cursor-not-allowed text-muted-foreground/40"
            )}
          >
            <ChevronLeft className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="min-w-0 truncate">
              {prevEntry ? prevEntry.section?.title ?? prevEntry.module.title : "Start"}
            </span>
          </button>
          <button
            type="button"
            disabled={!nextEntry}
            onClick={() => nextEntry && select(nextEntry.module.id, nextEntry.section?.id ?? null)}
            className={cn(
              "flex min-w-0 max-w-[45%] items-center justify-end gap-1.5 rounded-lg border border-border px-3 py-2 text-right text-xs font-medium transition-colors",
              nextEntry
                ? "text-foreground hover:bg-muted"
                : "cursor-not-allowed text-muted-foreground/40"
            )}
          >
            <span className="min-w-0 truncate">
              {nextEntry ? nextEntry.section?.title ?? nextEntry.module.title : "End"}
            </span>
            <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
