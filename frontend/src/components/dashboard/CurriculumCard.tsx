"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUpRight,
  BookOpen,
  Layers,
  MoreHorizontal,
  Pencil,
  Star,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
// Plain markup/Framer Motion, no mermaid/@xyflow/react — safe to statically import
// (see RenameCurriculumDialog's own comment / frontend/CLAUDE.md's ssr:false rule).
import { RenameCurriculumDialog } from "@/components/studio/curriculum/RenameCurriculumDialog";
import { curriculaApi, ApiError } from "@/lib/api";
import { timeAgo, cn } from "@/lib/utils";
import type { CurriculumSummary } from "@/lib/types";

// Popover menu width in px, matching the `w-56` class below — used to compute/clamp
// its open position from either trigger (button click or right-click).
const MENU_WIDTH = 224;

const STATUS_META: Record<
  CurriculumSummary["status"],
  { label: string; variant: "default" | "success" | "warning" | "destructive" | "info" | "outline" }
> = {
  researching: { label: "Researching", variant: "info" },
  planning: { label: "Planning", variant: "info" },
  awaiting_approval: { label: "Awaiting approval", variant: "warning" },
  writing: { label: "Writing", variant: "warning" },
  reviewing: { label: "Reviewing", variant: "info" },
  ready: { label: "Ready", variant: "success" },
  error: { label: "Error", variant: "destructive" },
};

interface CurriculumCardProps {
  curriculum: CurriculumSummary;
  onDeleted: (id: string) => void;
  /** Called when the star button is clicked; parent owns the optimistic update + PATCH. */
  onToggleFavorite: (id: string, favorite: boolean) => void;
  /** Called with the PATCH response after a successful rename, so the parent can update its list. */
  onRenamed: (updated: CurriculumSummary) => void;
}

/**
 * A single curriculum tile in the dashboard grid. Renders the title, the
 * agent-written description (falling back to the originating user prompt for
 * legacy curricula or pre-plan phases), a status badge (mapped from
 * `CurriculumSummary["status"]` via `STATUS_META`), and — while the agent is
 * still generating (researching/planning/writing/reviewing) — an animated
 * progress bar driven by `curriculum.progress`. Clicking the card navigates
 * to the studio for its conversation; the star button toggles
 * `curriculum.favorite` via `onToggleFavorite` (always visible + filled
 * yellow once favorited, hover-reveal otherwise). A `MoreHorizontal` "…"
 * button (hover-reveal, neutral styling) — also openable by right-clicking
 * anywhere on the card — opens a shared popover menu with Open in new tab,
 * Add/Remove favorites, Rename (opens `RenameCurriculumDialog`), and a
 * destructive Delete Curriculum item that opens the existing `ConfirmDialog`
 * flow (`curriculaApi.remove` then `onDeleted`). This component holds no
 * list state itself — all mutations bubble up via callbacks.
 */
export function CurriculumCard({ curriculum, onDeleted, onToggleFavorite, onRenamed }: CurriculumCardProps) {
  const router = useRouter();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  // Shared popover menu position; null = closed. Set by either the "…" button click
  // or a right-click anywhere on the card (see onContextMenu on <Card> below).
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // Also checked in the outside-mousedown handler below so the "…" button's own
  // mousedown doesn't close the menu right before its click handler toggles it —
  // that would make the button's click always reopen rather than actually toggle.
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const status = STATUS_META[curriculum.status];

  // Clamp a candidate menu position to stay within the viewport (menu is ~224px wide,
  // ~200px tall — matches MENU_WIDTH/the estimate used for right-click positioning).
  function clamp(x: number, y: number) {
    return {
      x: Math.min(x, window.innerWidth - MENU_WIDTH - 8),
      y: Math.min(y, window.innerHeight - 200),
    };
  }

  // Closing behavior while the menu is open: outside mousedown, Escape, and
  // scroll/resize (the menu is fixed-positioned so it would otherwise drift off
  // its trigger). Only registered while open to avoid leaking listeners.
  useEffect(() => {
    if (!menuPos) return;
    function onMouseDown(e: MouseEvent) {
      const target = e.target as Node;
      const insideMenu = menuRef.current?.contains(target);
      const insideButton = menuButtonRef.current?.contains(target);
      if (!insideMenu && !insideButton) setMenuPos(null);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuPos(null);
    }
    function onScrollOrResize() {
      setMenuPos(null);
    }
    document.addEventListener("mousedown", onMouseDown);
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScrollOrResize, { capture: true });
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScrollOrResize, { capture: true });
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [menuPos]);
  // "reviewing" counts as generating too — the agent is still actively editing sections.
  const isGenerating = ["researching", "planning", "writing", "reviewing"].includes(curriculum.status);
  const progressPct =
    curriculum.progress.total_tasks > 0
      ? Math.round((curriculum.progress.completed_tasks / curriculum.progress.total_tasks) * 100)
      : 0;

  async function handleDelete() {
    setDeleting(true);
    try {
      await curriculaApi.remove(curriculum.id);
      onDeleted(curriculum.id);
      toast.success("Curriculum deleted");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to delete");
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  // "…" button trigger: toggle open/closed at a position anchored below the button.
  // The outside-mousedown handler above excludes this button from closing the menu,
  // so this toggle actually flips state rather than always reopening.
  function handleMenuButtonClick(e: React.MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    if (menuPos) {
      setMenuPos(null);
      return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    setMenuPos(clamp(rect.right - MENU_WIDTH, rect.bottom + 4));
  }

  // Right-click trigger: open at the cursor instead of toggling (a second right-click
  // just repositions, matching native context-menu behavior).
  function handleContextMenu(e: React.MouseEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setMenuPos(clamp(e.clientX, e.clientY));
  }

  return (
    <>
      <motion.div
        layout
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96 }}
        transition={{ duration: 0.25 }}
      >
        <Card
          role="button"
          tabIndex={0}
          onClick={() => router.push(`/studio/${curriculum.conversation_id}`)}
          onKeyDown={(e) => {
            if (e.key === "Enter") router.push(`/studio/${curriculum.conversation_id}`);
          }}
          onContextMenu={handleContextMenu}
          className="group flex h-full cursor-pointer flex-col gap-3 p-5 transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <div className="flex items-start justify-between gap-2">
            <span className="text-2xl leading-none">{curriculum.emoji ?? "📘"}</span>
            <div className="flex items-center gap-0.5">
              <button
                ref={menuButtonRef}
                type="button"
                aria-label={`More options for ${curriculum.title}`}
                aria-haspopup="menu"
                onClick={handleMenuButtonClick}
                className={cn(
                  "rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100",
                  // Force-visible while the menu is open so it doesn't fade out mid-interaction.
                  menuPos && "opacity-100"
                )}
              >
                <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label={curriculum.favorite ? `Unfavorite ${curriculum.title}` : `Favorite ${curriculum.title}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleFavorite(curriculum.id, !curriculum.favorite);
                }}
                className={cn(
                  "rounded-md p-1.5 transition-opacity hover:bg-amber-400/10 hover:text-amber-400",
                  // Favorited: always visible + filled yellow (explicit user request, fine in both themes).
                  // Not favorited: same hover-reveal pattern as the trash button.
                  curriculum.favorite
                    ? "text-amber-400"
                    : "text-muted-foreground opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
                )}
              >
                <Star
                  className={cn("h-4 w-4", curriculum.favorite && "fill-amber-400 text-amber-400")}
                  aria-hidden="true"
                />
              </button>
            </div>
          </div>

          <div className="flex-1">
            <h3 className="font-semibold leading-snug line-clamp-2">{curriculum.title}</h3>
            {/* Falls back to user_prompt for legacy curricula or before a plan is first proposed. */}
            <p className="mt-1 text-xs text-muted-foreground line-clamp-3">
              {curriculum.description || curriculum.user_prompt}
            </p>
          </div>

          <Badge variant={status.variant} className="w-fit">
            {status.label}
          </Badge>

          {isGenerating && (
            <div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <motion.div
                  className="h-full rounded-full bg-accent"
                  initial={{ width: 0 }}
                  animate={{ width: `${progressPct}%` }}
                  transition={{ duration: 0.4 }}
                />
              </div>
              <p className="mt-1 truncate text-[11px] text-muted-foreground">
                {curriculum.progress.detail || "Working…"}
              </p>
            </div>
          )}

          <div className="flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Layers className="h-3.5 w-3.5" aria-hidden="true" />
              {curriculum.module_count} modules
            </span>
            <span className="flex items-center gap-1">
              <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
              {timeAgo(curriculum.updated_at)}
            </span>
          </div>
        </Card>
      </motion.div>

      {/* Shared popover menu, opened from either the "…" button or a right-click on the card.
          Fixed + positioned via inline style (menuPos); click/context-menu handlers on the
          container stop propagation so interacting with it never bubbles to the card's nav. */}
      <AnimatePresence>
        {menuPos && (
          <motion.div
            ref={menuRef}
            role="menu"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            style={{ left: menuPos.x, top: menuPos.y }}
            className="fixed z-50 w-56 overflow-hidden rounded-xl border border-border bg-popover py-1 shadow-lg"
            onClick={(e) => e.stopPropagation()}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                window.open(`/studio/${curriculum.conversation_id}`, "_blank", "noopener,noreferrer");
                setMenuPos(null);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
            >
              <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              Open in new tab
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                onToggleFavorite(curriculum.id, !curriculum.favorite);
                setMenuPos(null);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
            >
              <Star
                className={cn("h-4 w-4", curriculum.favorite && "fill-amber-400 text-amber-400")}
                aria-hidden="true"
              />
              {curriculum.favorite ? "Remove from favorites" : "Add to favorites"}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setRenameOpen(true);
                setMenuPos(null);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
            >
              <Pencil className="h-4 w-4" aria-hidden="true" />
              Rename
            </button>
            <div className="my-1 border-t border-border" />
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setConfirmOpen(true);
                setMenuPos(null);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-destructive hover:bg-destructive/10"
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              Delete Curriculum
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <ConfirmDialog
        open={confirmOpen}
        title="Delete this curriculum?"
        description={`"${curriculum.title}" and all its modules will be permanently deleted.`}
        confirmLabel="Delete"
        destructive
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setConfirmOpen(false)}
      />

      <RenameCurriculumDialog
        open={renameOpen}
        curriculum={{ id: curriculum.id, title: curriculum.title, description: curriculum.description }}
        onClose={() => setRenameOpen(false)}
        onSaved={onRenamed}
      />
    </>
  );
}
