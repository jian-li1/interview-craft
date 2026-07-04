"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ChevronDown, Circle, List, Loader2 } from "lucide-react";
import { SectionContent } from "@/components/studio/curriculum/SectionContent";
import { cn } from "@/lib/utils";
import type { CurriculumFull, ModuleStatus, SectionStatus } from "@/lib/types";

interface ReaderViewProps {
  curriculum: CurriculumFull;
  activeModuleOrder: number | null;
  onExplain: (prompt: string) => void;
}

const STATUS_ICON: Record<ModuleStatus | SectionStatus, typeof Circle> = {
  planned: Circle,
  writing: Loader2,
  complete: CheckCircle2,
};

function statusClasses(status: ModuleStatus | SectionStatus): string {
  if (status === "complete") return "text-success";
  if (status === "writing") return "text-accent";
  return "text-muted-foreground";
}

/**
 * Reader view: a left mini-TOC (modules -> sections, with status icons) and a
 * scrollable content area rendering each section's markdown. Selecting a TOC
 * entry scrolls the corresponding section into view.
 */
export function ReaderView({ curriculum, activeModuleOrder, onExplain }: ReaderViewProps) {
  const modules = useMemo(
    () => [...curriculum.modules].sort((a, b) => a.order - b.order),
    [curriculum.modules]
  );
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [activeModuleId, setActiveModuleId] = useState<string | null>(null);
  const [tocOpen, setTocOpen] = useState(false);
  const tocRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activeModuleOrder == null) return;
    const mod = modules.find((m) => m.order === activeModuleOrder);
    if (!mod) return;
    setActiveModuleId(mod.id);
    const el = document.getElementById(`module-${mod.id}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [activeModuleOrder, modules]);

  useEffect(() => {
    if (!tocOpen) return;
    function onClick(e: MouseEvent) {
      if (tocRef.current && !tocRef.current.contains(e.target as Node)) setTocOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [tocOpen]);

  function scrollToSection(sectionId: string, moduleId: string) {
    setActiveSectionId(sectionId);
    setActiveModuleId(moduleId);
    setTocOpen(false);
    document.getElementById(`section-${sectionId}`)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }

  const currentModule = modules.find((m) => m.id === activeModuleId) ?? modules[0] ?? null;

  if (modules.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-muted-foreground">
        No modules yet — the outline will populate here once the agent starts writing.
      </div>
    );
  }

  const tocList = (
    <ul className="space-y-3">
      {modules.map((mod) => {
        const ModIcon = STATUS_ICON[mod.status];
        return (
          <li key={mod.id}>
            <div className="flex items-center gap-1.5 text-xs font-semibold">
              <ModIcon
                className={cn("h-3.5 w-3.5 shrink-0", statusClasses(mod.status), mod.status === "writing" && "animate-spin")}
                aria-hidden="true"
              />
              <span className="truncate">
                {mod.order}. {mod.title}
              </span>
            </div>
            {mod.sections.length > 0 && (
              <ul className="mt-1.5 space-y-1 border-l border-border pl-4">
                {[...mod.sections]
                  .sort((a, b) => a.order - b.order)
                  .map((sec) => {
                    const SecIcon = STATUS_ICON[sec.status];
                    return (
                      <li key={sec.id}>
                        <button
                          type="button"
                          onClick={() => scrollToSection(sec.id, mod.id)}
                          className={cn(
                            "flex w-full items-center gap-1.5 truncate rounded-md px-1.5 py-1 text-left text-xs text-muted-foreground hover:bg-muted hover:text-foreground",
                            activeSectionId === sec.id && "bg-accent-soft text-accent"
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
            {currentModule ? `${currentModule.order}. ${currentModule.title}` : "Contents"}
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

      {/* Content */}
      <div className="min-w-0 flex-1 overflow-y-auto p-6 scrollbar-thin">
        <AnimatePresence initial={false}>
          {modules.map((mod) => (
            <motion.section
              key={mod.id}
              id={`module-${mod.id}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
              className="mb-10 scroll-mt-4"
            >
              <div className="mb-4 flex items-start justify-between gap-3 border-b border-border pb-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-accent">
                    Module {mod.order}
                  </p>
                  <h2 className="text-xl font-semibold">{mod.title}</h2>
                  {mod.summary && (
                    <p className="mt-1 text-sm text-muted-foreground">{mod.summary}</p>
                  )}
                </div>
              </div>

              {mod.sections.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                  {mod.status === "planned" ? "This module hasn't been written yet." : "Writing in progress…"}
                </div>
              ) : (
                [...mod.sections]
                  .sort((a, b) => a.order - b.order)
                  .map((sec) => (
                    <div key={sec.id} id={`section-${sec.id}`} className="mb-8 scroll-mt-4">
                      <h3 className="mb-2 flex items-center gap-2 text-base font-semibold">
                        {sec.title}
                      </h3>
                      {sec.status === "planned" ? (
                        <p className="text-sm text-muted-foreground">Not written yet.</p>
                      ) : (
                        <SectionContent section={sec} onExplain={onExplain} />
                      )}
                    </div>
                  ))
              )}
            </motion.section>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
