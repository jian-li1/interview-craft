"use client";

import { useCallback, useRef, useState } from "react";

/** Options for `usePanelResize` — one instance per resizable panel/divider pair. */
interface UsePanelResizeOptions {
  /** localStorage key for persisting the user's chosen width across visits. */
  storageKey: string;
  /** Initial width (px) used when no persisted value exists. */
  defaultWidth: number;
  /** Lower clamp bound (px). */
  minWidth: number;
  /** Upper clamp bound (px), hard cap regardless of viewport size. */
  maxWidth: number;
  /** Width is also capped to `window.innerWidth * maxViewportRatio`, whichever is smaller. */
  maxViewportRatio: number;
  /** Keyboard nudge step (px) for ArrowLeft/ArrowRight on the divider. Defaults to 24. */
  arrowStep?: number;
}

/** Return shape: current width, drag state, and handlers/attrs to spread onto the divider element. */
interface UsePanelResizeResult {
  /** Current panel width in px. */
  width: number;
  /** True while the divider is being pointer-dragged. */
  isDragging: boolean;
  /** Spread directly onto the `role="separator"` divider element. */
  separatorProps: {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => void;
    onPointerMove: (e: React.PointerEvent<HTMLDivElement>) => void;
    onPointerUp: (e: React.PointerEvent<HTMLDivElement>) => void;
    onPointerCancel: (e: React.PointerEvent<HTMLDivElement>) => void;
    onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
    role: "separator";
    "aria-orientation": "vertical";
    tabIndex: number;
  };
}

/**
 * Shared drag/keyboard-resize behavior for a panel with an adjacent divider
 * (extracted from the studio page's chat/curriculum split so `ReaderView`'s
 * TOC sidebar can reuse the exact same interaction). Pointer-drag (capture on
 * the divider so the drag survives leaving its narrow hit area) and
 * ArrowLeft/ArrowRight keyboard nudges both clamp to
 * `[minWidth, min(maxWidth, innerWidth * maxViewportRatio)]` and persist to
 * `localStorage[storageKey]`. Callers own the divider's visual classes and
 * `aria-label` — this hook only returns behavior, not markup.
 */
export function usePanelResize({
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth,
  maxViewportRatio,
  arrowStep = 24,
}: UsePanelResizeOptions): UsePanelResizeResult {
  // Clamp helper shared by pointer-drag and keyboard resize paths; closes over this call's options.
  const clamp = useCallback(
    (value: number): number => {
      const cappedMax =
        typeof window === "undefined" ? maxWidth : Math.min(maxWidth, window.innerWidth * maxViewportRatio);
      return Math.min(Math.max(value, minWidth), cappedMax);
    },
    [minWidth, maxWidth, maxViewportRatio]
  );

  // Lazy-init from localStorage (clamped) so the user's last drag persists across visits.
  const [width, setWidth] = useState<number>(() => {
    if (typeof window === "undefined") return defaultWidth;
    const stored = window.localStorage.getItem(storageKey);
    const parsed = stored ? Number(stored) : NaN;
    return Number.isFinite(parsed) ? clamp(parsed) : defaultWidth;
  });
  // True while the divider is being pointer-dragged; callers use this to disable
  // pointer events on the panels so a fast drag doesn't get swallowed mid-move.
  const [isDragging, setIsDragging] = useState(false);
  // Drag bookkeeping kept in refs (not state) since they don't need renders.
  const dragStartXRef = useRef(0);
  const dragStartWidthRef = useRef(defaultWidth);

  // Pointer-driven resize: capture the pointer on the divider itself so drag
  // continues even if the cursor leaves the narrow hit area mid-move.
  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      dragStartXRef.current = e.clientX;
      dragStartWidthRef.current = width;
      setIsDragging(true);
      // Prevent text selection/cursor flicker over iframes/canvas while dragging.
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
    },
    [width]
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!isDragging) return;
      const delta = e.clientX - dragStartXRef.current;
      setWidth(clamp(dragStartWidthRef.current + delta));
    },
    [isDragging, clamp]
  );

  const endDrag = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!isDragging) return;
      e.currentTarget.releasePointerCapture(e.pointerId);
      setIsDragging(false);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      // Persist the final width so it survives a reload/revisit.
      setWidth((current) => {
        window.localStorage.setItem(storageKey, String(current));
        return current;
      });
    },
    [isDragging, storageKey]
  );

  // Keyboard resize: ArrowLeft/ArrowRight nudge by a fixed step, clamped and persisted.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const step = e.key === "ArrowRight" ? arrowStep : -arrowStep;
      setWidth((current) => {
        const next = clamp(current + step);
        window.localStorage.setItem(storageKey, String(next));
        return next;
      });
    },
    [arrowStep, clamp, storageKey]
  );

  return {
    width,
    isDragging,
    separatorProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onKeyDown,
      role: "separator",
      "aria-orientation": "vertical",
      tabIndex: 0,
    },
  };
}
