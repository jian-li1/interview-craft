"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Search, X } from "lucide-react";
import { flattenCurriculum } from "@/lib/reader";
import type { CurriculumFull, ModuleOut, SectionOut } from "@/lib/types";

interface CurriculumSearchDialogProps {
  open: boolean;
  curriculum: CurriculumFull;
  onClose: () => void;
  onSelect: (moduleId: string, sectionId: string) => void;
}

/** One searchable row: a module/section pair plus its markdown stripped to plain text. */
interface SearchRow {
  module: ModuleOut;
  section: SectionOut;
  plainText: string;
}

/**
 * Strips a section's `content_markdown` down to plain, searchable/displayable text.
 * Deliberately a handful of simple regexes — this is display/search normalization,
 * not a full markdown parser, so edge cases (nested emphasis, tables, etc.) are fine
 * to render slightly imperfectly.
 */
function stripMarkdown(md: string): string {
  return md
    .replace(/```[a-zA-Z0-9]*\n?/g, "") // fence markers (with optional language tag)
    .replace(/^#{1,6}\s+/gm, "") // heading prefixes
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "") // images — drop entirely
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // links -> link text
    .replace(/\[\^\d+\]/g, "") // footnote refs
    .replace(/[*_`]+/g, "") // emphasis/inline-code markers
    .replace(/\s+/g, " ") // collapse all whitespace runs
    .trim();
}

/**
 * Splits `text` on case-insensitive occurrences of `query` and wraps each match in a
 * highlighted `<span>`. Returns the original text unchanged (as a plain string) when
 * `query` is empty, since an empty split would otherwise wrap every character.
 */
function highlightMatches(text: string, query: string): ReactNode {
  // Trim once and reuse `q` for both the regex source and the per-part comparison —
  // building the regex from the untrimmed query while comparing against the trimmed
  // one meant a query with leading/trailing whitespace never matched any split part.
  const q = query.trim();
  if (!q) return text;
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === q.toLowerCase() ? (
      <span key={i} className="rounded-[3px] bg-accent-soft px-0.5 text-accent">
        {part}
      </span>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    )
  );
}

/**
 * Builds a display snippet around the first match in `plainText` (~40 chars of context
 * before, ~160 total), snapping the start forward to the next space so words aren't cut
 * mid-word. Falls back to the first ~160 chars when only the title matched (or the
 * section is unwritten, in which case it returns "").
 */
function buildSnippet(plainText: string, query: string): string {
  if (!plainText) return "";
  const q = query.trim().toLowerCase();
  const idx = plainText.toLowerCase().indexOf(q);
  if (idx === -1) {
    // Title-only match: lead with the section's opening text instead.
    return plainText.length > 160 ? `${plainText.slice(0, 160)}…` : plainText;
  }
  let start = Math.max(0, idx - 40);
  if (start > 0) {
    const nextSpace = plainText.indexOf(" ", start);
    if (nextSpace !== -1 && nextSpace < idx) start = nextSpace + 1;
  }
  const end = Math.min(plainText.length, start + 160);
  const prefix = start > 0 ? "…" : "";
  const suffix = end < plainText.length ? "…" : "";
  return `${prefix}${plainText.slice(start, end)}${suffix}`;
}

/**
 * Command-palette-style search dialog for full-text search across every written section
 * of the open curriculum. Pure markup + Framer Motion (no mermaid/@xyflow/react), so it's
 * safe to statically import into `CurriculumPanel` — unlike `WorkflowView`/`ReaderView`,
 * it doesn't fall under the `ssr:false` rule (same reasoning as `RenameCurriculumDialog`).
 *
 * Matching is case-insensitive substring against section title OR plain-text content
 * (markdown stripped via `stripMarkdown`); an empty query shows a hint instead of results.
 * Clicking a result calls `onSelect(moduleId, sectionId)` — the caller (CurriculumPanel)
 * is responsible for switching to the reader view on that section and closing the dialog.
 */
export function CurriculumSearchDialog({ open, curriculum, onClose, onSelect }: CurriculumSearchDialogProps) {
  const [query, setQuery] = useState("");

  // Reseed the query every time the dialog opens, so reopening never shows a stale search.
  useEffect(() => {
    if (open) setQuery("");
  }, [open]);

  // Escape closes, matching RenameCurriculumDialog's behavior.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Flatten the curriculum into searchable rows (only entries with a real section),
  // pre-computing each section's stripped plain text once per curriculum change.
  const rows = useMemo<SearchRow[]>(() => {
    return flattenCurriculum(curriculum)
      .filter((entry): entry is { module: ModuleOut; section: SectionOut } => entry.section !== null)
      .map((entry) => ({
        module: entry.module,
        section: entry.section,
        plainText: stripMarkdown(entry.section.content_markdown),
      }));
  }, [curriculum]);

  // Filter rows by the current query — empty query intentionally yields no rows (hint shown instead).
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return rows.filter(
      (row) => row.section.title.toLowerCase().includes(q) || row.plainText.toLowerCase().includes(q)
    );
  }, [rows, query]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            initial={{ opacity: 0, scale: 0.97, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -8 }}
            transition={{ duration: 0.15 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
          >
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
                placeholder="Search this curriculum"
                aria-label="Search this curriculum"
                className="w-full bg-transparent text-sm focus:outline-none placeholder:text-muted-foreground"
              />
              {/* Clears the query first if non-empty; only closes the dialog once already empty. */}
              <button
                type="button"
                aria-label={query ? "Clear search" : "Close search"}
                onClick={() => (query ? setQuery("") : onClose())}
                className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>

            <div className="max-h-[50vh] overflow-y-auto py-2 scrollbar-thin">
              {!query.trim() ? (
                <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                  Search across every section of this curriculum.
                </p>
              ) : results.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                  No matches for &quot;{query.trim()}&quot;.
                </p>
              ) : (
                results.map((row) => {
                  const snippet = buildSnippet(row.plainText, query);
                  return (
                    <button
                      // section.id is only unique PER MODULE (see ReaderView's isActive
                      // check) — composite with module.id to avoid duplicate React keys
                      // when the same section id appears under two different modules.
                      key={`${row.module.id}-${row.section.id}`}
                      type="button"
                      onClick={() => onSelect(row.module.id, row.section.id)}
                      className="w-full px-4 py-2.5 text-left hover:bg-muted"
                    >
                      {/* order is 0-based; display 1-based (matches ReaderView's Module label) */}
                      <p className="text-[11px] text-muted-foreground">Module {row.module.order + 1}</p>
                      <p className="text-sm font-medium">{highlightMatches(row.section.title, query)}</p>
                      {snippet && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                          {highlightMatches(snippet, query)}
                        </p>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
