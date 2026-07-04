"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { BookOpen, Loader2, Workflow as WorkflowIcon } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { ActivityFeed } from "@/components/studio/curriculum/ActivityFeed";
import { useChatStore } from "@/stores/useChatStore";
import { useCurriculumStore } from "@/stores/useCurriculumStore";

// Workflow view uses @xyflow/react + ReaderView renders Mermaid — both need to
// stay client-only, so keep the whole panel body dynamic (ssr: false) per
// spec 03 §5 to avoid hydration warnings.
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

export function CurriculumPanel({ curriculumId, onExplain }: CurriculumPanelProps) {
  const curriculum = useCurriculumStore((s) => s.curriculum);
  const loading = useCurriculumStore((s) => s.loading);
  const error = useCurriculumStore((s) => s.error);
  const fetchCurriculum = useCurriculumStore((s) => s.fetchCurriculum);

  const activity = useChatStore((s) => s.activity);
  const phaseLabel = useChatStore((s) => s.phaseLabel);

  const [view, setView] = useState<View>("workflow");
  const [activeModuleOrder, setActiveModuleOrder] = useState<number | null>(null);

  useEffect(() => {
    if (curriculumId) void fetchCurriculum(curriculumId);
  }, [curriculumId, fetchCurriculum]);

  function handleSelectModule(order: number) {
    setActiveModuleOrder(order);
    setView("reader");
  }

  const hasContent = Boolean(curriculum && curriculum.modules.length > 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {curriculum ? `${curriculum.emoji ?? "📘"} ${curriculum.title}` : "Curriculum"}
          </p>
        </div>
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
            <ActivityFeed activity={activity} phaseLabel={phaseLabel} />
          </motion.div>
        ) : view === "workflow" ? (
          <WorkflowView curriculum={curriculum!} onSelectModule={handleSelectModule} />
        ) : (
          <ReaderView
            curriculum={curriculum!}
            activeModuleOrder={activeModuleOrder}
            onExplain={onExplain}
          />
        )}
      </div>
    </div>
  );
}
