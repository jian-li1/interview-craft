"use client";

import dynamic from "next/dynamic";
import { memo, useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { BookOpen, Loader2, Maximize2, Minimize2, Workflow as WorkflowIcon } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { ActivityFeed } from "@/components/studio/curriculum/ActivityFeed";
import { useChatStore } from "@/stores/useChatStore";
import { useCurriculumStore } from "@/stores/useCurriculumStore";

// *** THIS is the ssr:false dynamic-import boundary referenced by root/frontend
// CLAUDE.md's "ssr:false rule" for BOTH libraries that must never touch the
// server-rendered tree:
//   - WorkflowView imports `@xyflow/react` (React Flow) at its top level —
//     that library reads/writes DOM layout (measuring nodes, computing the
//     canvas viewport, etc.) and has no meaningful server-side render.
//   - ReaderView transitively renders Mermaid diagrams (ReaderView ->
//     SectionContent -> MermaidDiagram), and Mermaid itself is only ever
//     `import()`-ed at runtime inside a useEffect (see MermaidDiagram.tsx) —
//     but ReaderView still needs to be excluded from SSR here too, since its
//     child tree assumes a browser environment throughout.
// Wrapping both in `next/dynamic(..., { ssr: false })` at THIS single
// boundary means neither module is ever pulled into the server bundle or
// hydrated against server-rendered markup — a plain top-level `import`
// of either component elsewhere would break the Next.js build (per spec 03
// §5) or produce hydration mismatches, since their real DOM (React Flow's
// canvas nodes, Mermaid's rendered SVG) only exists client-side.
const WorkflowView = dynamic(
  () => import("@/components/studio/curriculum/WorkflowView").then((m) => m.WorkflowView),
  { ssr: false }
);
const ReaderView = dynamic(
  () => import("@/components/studio/curriculum/ReaderView").then((m) => m.ReaderView),
  { ssr: false }
);

interface CurriculumPanelProps {
  curriculumId: string | null;
  onExplain: (prompt: string) => void;
}

type View = "workflow" | "reader";

export interface ActiveSelection {
  moduleId: string;
  sectionId: string | null;
}

function CurriculumPanelImpl({ curriculumId, onExplain }: CurriculumPanelProps) {
  const curriculum = useCurriculumStore((s) => s.curriculum);
  const loading = useCurriculumStore((s) => s.loading);
  const error = useCurriculumStore((s) => s.error);
  const fetchCurriculum = useCurriculumStore((s) => s.fetchCurriculum);
  // Full-screen focus mode: hides app chrome + chat (see AppShell/StudioPage).
  const focusMode = useCurriculumStore((s) => s.focusMode);
  const setFocusMode = useCurriculumStore((s) => s.setFocusMode);

  const activity = useChatStore((s) => s.activity);
  const phaseLabel = useChatStore((s) => s.phaseLabel);
  const plan = useChatStore((s) => s.plan);

  const [view, setView] = useState<View>("workflow");
  const [activeSelection, setActiveSelection] = useState<ActiveSelection | null>(null);

  useEffect(() => {
    // Reset local view state whenever the curriculum identity changes so the
    // reader never shows a section carried over from the previous
    // curriculum, and the panel always lands back on the workflow view.
    setView("workflow");
    setActiveSelection(null);
    if (curriculumId) void fetchCurriculum(curriculumId);
  }, [curriculumId, fetchCurriculum]);

  // Safety net: force-clear focus mode on unmount so navigating away from the
  // studio never leaves the app shell (sidebar/header) permanently hidden.
  useEffect(() => {
    return () => setFocusMode(false);
  }, [setFocusMode]);

  // While focus mode is active, Escape exits it — unless a modal (e.g. the
  // Mermaid fullscreen viewer, which sets aria-modal="true") is open, in
  // which case Escape should close that modal instead.
  useEffect(() => {
    if (!focusMode) return;
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (document.querySelector('[aria-modal="true"]')) return; // let the open dialog handle Escape
      setFocusMode(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusMode, setFocusMode]);

  // Memoized: prevents identity churn that rebuilds all React Flow nodes on every
  // CurriculumPanel render (including unrelated chat-store updates), which caused
  // max-update-depth errors. Called via WorkflowView's onNodeClick (registered on
  // <ReactFlow>, not threaded into node data) when a module card is clicked.
  const handleSelectModule = useCallback(
    (moduleId: string) => {
      const mod = curriculum?.modules.find((m) => m.id === moduleId);
      const firstSection = mod
        ? [...mod.sections].sort((a, b) => a.order - b.order)[0] ?? null
        : null;
      setActiveSelection({ moduleId, sectionId: firstSection?.id ?? null });
      setView("reader");
    },
    [curriculum]
  );

  // useCallback (no deps: only calls the local setter) keeps ReaderView's
  // onSelectSection prop referentially stable across renders.
  const handleSelectSection = useCallback((moduleId: string, sectionId: string | null) => {
    setActiveSelection({ moduleId, sectionId });
  }, []);

  const hasContent = Boolean(curriculum && curriculum.modules.length > 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {curriculum ? `${curriculum.emoji ?? "📘"} ${curriculum.title}` : "Curriculum"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Tabs value={view} onValueChange={(v) => setView(v as View)}>
            <TabsList aria-label="Curriculum view">
              <TabsTrigger value="workflow">
                <span className="flex items-center gap-1.5">
                  <WorkflowIcon className="h-3.5 w-3.5" aria-hidden="true" />
                  Workflow
                </span>
              </TabsTrigger>
              <TabsTrigger value="reader">
                <span className="flex items-center gap-1.5">
                  <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
                  Reader
                </span>
              </TabsTrigger>
            </TabsList>
          </Tabs>
          {/* Full-screen focus toggle: hides app header/sidebar/chat, leaving only this panel. */}
          <button
            type="button"
            onClick={() => setFocusMode(!focusMode)}
            aria-label={focusMode ? "Exit full screen" : "Focus curriculum (full screen)"}
            title={focusMode ? "Exit full screen" : "Focus curriculum (full screen)"}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {focusMode ? (
              <Minimize2 className="h-4 w-4" aria-hidden="true" />
            ) : (
              <Maximize2 className="h-4 w-4" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {!curriculumId ? (
          <div className="flex h-full items-center justify-center p-8">
            <EmptyState
              title="No curriculum yet"
              description="Send a message describing what you're preparing for, and the agent will start researching."
            />
          </div>
        ) : loading && !curriculum ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Loading curriculum" />
          </div>
        ) : error && !curriculum ? (
          <div className="flex h-full items-center justify-center p-8">
            <EmptyState title="Couldn't load this curriculum" description={error} />
          </div>
        ) : !hasContent ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.25 }}
            className="h-full"
          >
            <ActivityFeed activity={activity} phaseLabel={phaseLabel} plan={plan} />
          </motion.div>
        ) : view === "workflow" ? (
          <WorkflowView curriculum={curriculum!} onSelectModule={handleSelectModule} />
        ) : (
          <ReaderView
            curriculum={curriculum!}
            activeSelection={activeSelection}
            onSelectSection={handleSelectSection}
            onExplain={onExplain}
          />
        )}
      </div>
    </div>
  );
}

// memo: blocks re-renders driven by parent (StudioPage) chat-store churn,
// since this component's props (curriculumId string, onExplain now
// useCallback-stable) don't actually change on every chat message/delta.
export const CurriculumPanel = memo(CurriculumPanelImpl);
