"use client";

import { memo, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useTheme } from "next-themes";
import { AlertTriangle, Check, Copy, Loader2, Maximize2, RotateCcw, X, ZoomIn, ZoomOut } from "lucide-react";
// Static import is fine here (unlike mermaid) — this is a plain React component with no
// document/DOM-measurement calls at import time, so it's safe in the server bundle too.
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";
import { cn } from "@/lib/utils";

interface MermaidDiagramProps {
  /** Raw Mermaid diagram source (the fenced ```mermaid code block's contents), as extracted by SectionContent's custom `code` renderer. */
  chart: string;
}

/** A shape's explicit fill, parsed into 0-255 RGB channels. */
interface Rgb {
  r: number;
  g: number;
  b: number;
}

/**
 * Parses `#rgb`, `#rrggbb`, and `rgb(r,g,b)` color strings into RGB channels.
 * Returns `null` for anything else (`none`, `url(#...)`, `inherit`, CSS custom
 * properties, empty strings) so callers can treat those as "no explicit color".
 */
function parseColor(value: string): Rgb | null {
  const trimmed = value.trim();
  // #rgb or #rrggbb
  const hexMatch = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(trimmed);
  if (hexMatch) {
    const hex = hexMatch[1];
    // Expand shorthand #rgb to #rrggbb by duplicating each digit.
    const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex;
    return {
      r: parseInt(full.slice(0, 2), 16),
      g: parseInt(full.slice(2, 4), 16),
      b: parseInt(full.slice(4, 6), 16),
    };
  }
  // rgb(r, g, b)
  const rgbMatch = /^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i.exec(trimmed);
  if (rgbMatch) {
    return { r: Number(rgbMatch[1]), g: Number(rgbMatch[2]), b: Number(rgbMatch[3]) };
  }
  return null; // none / url(#...) / inherit / var(...) / unrecognized
}

/**
 * Mermaid's built-in `dark` theme paints every node/cluster label a uniform
 * light-gray, on the assumption that node backgrounds are also theme-default.
 * Agent-generated diagrams routinely hardcode pastel `classDef`/`style` fills
 * (e.g. `fill:#e0f2e0`) for semantic grouping, and on those nodes the
 * light-gray label text becomes light-on-light and unreadable (the same
 * problem, inverted, can happen to a dark hardcoded fill in light theme).
 *
 * This walks the rendered SVG markup after the fact — outside React, on a
 * detached DOM — and for every `g.node`/`g.cluster` whose shape has an
 * *explicit* fill (attribute or inline `style`), recolors that group's
 * label text/HTML to whichever ink (near-black or near-white) contrasts
 * best against the fill. Shapes with no explicit fill (theme-default nodes)
 * are left untouched — they're already legible. Runs identically in both
 * themes since it only ever reacts to hardcoded fills, never theme defaults.
 */
function fixLabelContrastForHardcodedFills(svgMarkup: string): string {
  // Detached container so we can use querySelector/innerHTML without touching the live page.
  const host = document.createElement("div");
  host.innerHTML = svgMarkup;

  const groups = host.querySelectorAll<SVGGElement>("g.node, g.cluster");
  groups.forEach((group) => {
    // First shape element inside the group — mermaid always renders exactly one per node/cluster.
    const shape = group.querySelector<SVGGraphicsElement>("rect, circle, ellipse, polygon, path");
    if (!shape) return;

    // Inline `style` wins over the `fill` attribute in the actual render, so prefer it.
    const styleFill = shape.style.getPropertyValue("fill");
    const fillValue = styleFill || shape.getAttribute("fill") || "";
    const rgb = parseColor(fillValue);
    if (!rgb) return; // no explicit/parseable fill — theme-default node, leave it alone

    // Standard perceived-luminance formula; pick the ink with the stronger contrast.
    const luminance = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
    const ink = luminance > 0.5 ? "#1f2937" : "#f8fafc";

    // Mechanism 1: plain SVG text labels (edge labels, some node label modes).
    group.querySelectorAll<SVGElement>("text, tspan").forEach((el) => {
      el.style.setProperty("fill", ink, "important");
    });
    // Mechanism 2: HTML labels inside a <foreignObject> (mermaid's default node label markup).
    // `important` is required — mermaid injects a <style> sheet into the SVG that otherwise wins.
    group
      .querySelectorAll<HTMLElement>("foreignObject .nodeLabel, foreignObject .label, foreignObject span, foreignObject div, foreignObject p")
      .forEach((el) => {
        el.style.setProperty("color", ink, "important");
      });
  });

  return host.innerHTML;
}

/**
 * Legacy clipboard fallback (hidden textarea + `execCommand("copy")`) for
 * contexts where the async Clipboard API is unavailable or denied — e.g.
 * non-HTTPS origins or permission-restricted embedded panes. Returns whether
 * the copy actually succeeded so the caller can gate its "copied" feedback.
 */
function legacyCopyToClipboard(text: string): boolean {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed"; // keep it out of layout so appending never scrolls the page
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  let ok = false;
  try {
    ok = document.execCommand("copy"); // deprecated but the only path left when the async API is blocked
  } finally {
    document.body.removeChild(textarea);
  }
  return ok;
}

// Shared styling for the overlay icon buttons — mirrors ui/Button.tsx's ghost/icon treatment.
const controlButtonClass =
  "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

interface DiagramViewerProps {
  /** Post-processed SVG markup produced by mermaid.render + the contrast pass. */
  svg: string;
  /** Raw diagram source — needed by the copy-source control. */
  chart: string;
  /** Fullscreen (modal) mode: viewer fills its parent's height and centers the diagram vertically. */
  isFullscreen?: boolean;
  /** Inline mode only: opens the fullscreen modal; renders the Maximize2 control when set. */
  onExpand?: () => void;
  /** Fullscreen mode only: closes the modal; renders the X control when set. */
  onClose?: () => void;
}

/**
 * The shared pan/zoom viewer: TransformWrapper + overlay control cluster +
 * the SVG content. Rendered by both the inline card and the fullscreen modal
 * so controls and behavior stay identical and can't drift. Owns its own
 * `copied` state so each instance gives independent copy feedback. The
 * fullscreen instance mounts fresh on every open, so its transform naturally
 * starts at scale 1 — no zoom-state syncing with the inline instance.
 */
function DiagramViewer({ svg, chart, isFullscreen = false, onExpand, onClose }: DiagramViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false); // true briefly after a successful "copy source" click
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null); // pending "reset copied" timer, cleared on unmount/re-copy

  // Clear the pending "copied" reset timer on unmount so it never fires against an unmounted component.
  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    };
  }, []);

  // Copies the raw diagram source to the clipboard and flips the icon to a checkmark for ~1.5s.
  async function handleCopySource() {
    let ok = false;
    try {
      await navigator.clipboard.writeText(chart); // primary path: async Clipboard API
      ok = true;
    } catch {
      ok = legacyCopyToClipboard(chart); // API missing/denied (non-secure origin, embedded pane) — legacy fallback
    }
    if (!ok) return; // both paths failed — silent no-op, no false "copied" feedback
    setCopied(true);
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    copyTimeoutRef.current = setTimeout(() => setCopied(false), 1500);
  }

  return (
    // `relative` anchors the overlay cluster; fullscreen fills the modal panel's full height.
    <div className={cn("mermaid-container relative", isFullscreen && "h-full")}>
      <TransformWrapper
        minScale={0.4}
        maxScale={4}
        // Plain wheel zoom, no modifier key required. In smooth mode the lib zooms by
        // exp(step * |deltaY|), so step must be tiny: 0.004 ≈ 1.5x per mouse notch (deltaY 100).
        wheel={{ step: 0.004 }}
        doubleClick={{ mode: "zoomIn" }}
        limitToBounds={false} // allow panning large diagrams freely past their natural bounds
      >
        {({ zoomIn, zoomOut, resetTransform }) => (
          <>
            {/* Overlay control cluster: zoom in/out, reset, copy source, expand/close. */}
            <div className="absolute right-2 top-2 z-10 flex items-center gap-1 rounded-md border border-border bg-card/80 p-1 backdrop-blur">
              <button
                type="button"
                onClick={() => zoomIn()}
                aria-label="Zoom in"
                title="Zoom in"
                className={controlButtonClass}
              >
                <ZoomIn className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => zoomOut()}
                aria-label="Zoom out"
                title="Zoom out"
                className={controlButtonClass}
              >
                <ZoomOut className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => resetTransform()}
                aria-label="Reset view"
                title="Reset view"
                className={controlButtonClass}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={handleCopySource}
                aria-label="Copy diagram source"
                title="Copy diagram source"
                className={controlButtonClass}
              >
                {copied ? (
                  <Check className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Copy className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
              {/* Inline instance: expand into the fullscreen modal. */}
              {onExpand && (
                <button
                  type="button"
                  onClick={onExpand}
                  aria-label="Full screen"
                  title="Full screen"
                  className={controlButtonClass}
                >
                  <Maximize2 className="h-4 w-4" aria-hidden="true" />
                </button>
              )}
              {/* Fullscreen instance: the expand slot becomes a close affordance instead. */}
              {onClose && (
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close full screen"
                  title="Close full screen"
                  className={controlButtonClass}
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              )}
            </div>
            <TransformComponent
              // Inline styles (not classes) on both wrapper and content — the lib's CSS-module
              // width/height (fit-content) beats utility classes; fullscreen also claims full height.
              wrapperStyle={isFullscreen ? { width: "100%", height: "100%" } : { width: "100%" }}
              wrapperClass="cursor-grab active:cursor-grabbing" // grab affordance on the pannable viewport only
              contentStyle={isFullscreen ? { width: "100%", height: "100%" } : { width: "100%" }}
            >
              {/* w-full gives the svg's width:100% a definite basis (a shrink-to-fit flex item would make it circular and collapse); flex centers diagrams narrower than the card. */}
              <div
                ref={containerRef}
                // fullscreen: also center vertically and cap the svg's height so tall diagrams letterbox into the panel instead of clipping (global css only caps max-width)
                className={cn("flex w-full justify-center p-4", isFullscreen && "h-full items-center [&_svg]:max-h-full")}
                // eslint-disable-next-line react/no-danger -- mermaid's own sanitized SVG output, rendered in "strict" securityLevel
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            </TransformComponent>
          </>
        )}
      </TransformWrapper>
    </div>
  );
}

interface DiagramFullscreenModalProps {
  /** Whether the modal is shown; AnimatePresence animates it in/out on change. */
  open: boolean;
  /** Close callback — fired by Escape, backdrop click, and the viewer's X control. */
  onClose: () => void;
  /** SVG + source forwarded straight to the embedded DiagramViewer. */
  svg: string;
  chart: string;
}

/**
 * Near-full-viewport popup for a diagram (GitHub-style). Follows
 * ConfirmDialog's conventions — AnimatePresence fade backdrop, scale/fade
 * panel, Escape-to-close bound only while open, backdrop click closes with
 * panel clicks stopped — but renders through a portal (see inline comment)
 * and locks body scroll while open.
 */
function DiagramFullscreenModal({ open, onClose, svg, chart }: DiagramFullscreenModalProps) {
  // Escape-to-close, bound only while open (mirrors ConfirmDialog) so the listener never leaks.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Lock body scroll while the modal is open, restoring the previous value on close/unmount.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Portal to document.body: MermaidDiagram sits inside Framer-Motion-transformed ancestors in
  // ReaderView, and a CSS transform on an ancestor makes `position: fixed` resolve against that
  // ancestor instead of the viewport — without the portal the modal would be clipped/mispositioned.
  // Client-safe: this only renders from the success branch, which never renders during SSR (svg
  // state starts null and is only set by the client-side effect).
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose} // backdrop click closes; panel clicks are stopped below
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Diagram full screen view"
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ duration: 0.18 }}
            onClick={(e) => e.stopPropagation()} // keep panel clicks from bubbling to the closing backdrop
            className="relative h-[92vh] w-[95vw] overflow-hidden rounded-xl border border-border bg-card shadow-lg"
          >
            {/* Fresh viewer instance per open — transform starts at scale 1, no state syncing needed. */}
            <DiagramViewer svg={svg} chart={chart} isFullscreen onClose={onClose} />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}

/**
 * Renders a single Mermaid diagram client-side only. Re-renders whenever the
 * resolved color theme changes so diagrams stay legible in dark mode.
 *
 * *** THIS is the runtime `import()`-inside-`useEffect` pattern referenced by
 * root/frontend CLAUDE.md's "ssr:false rule" — the OTHER accepted way (besides
 * `next/dynamic(..., { ssr: false })` at a component boundary, see
 * CurriculumPanel.tsx) to keep a browser-only library out of the server
 * render. Mermaid's `render()` call touches `document`/canvas/SVG-measurement
 * APIs that don't exist during SSR, so the import itself is deferred to a
 * `useEffect` (which only ever runs client-side, after mount) rather than
 * being a top-level `import mermaid from "mermaid"` — a static import would
 * pull mermaid into the server bundle and either crash the server render or
 * bloat it for no benefit, since this component always needs a live browser
 * DOM to actually draw anything.
 *
 * On parse/render failure, degrades gracefully: instead of a destructive
 * error box, renders the raw chart source as a plain code block with a
 * small muted note. The parser error itself only goes to `console.warn`.
 *
 * Successful renders get a pan/zoom/reset/copy control cluster (react-zoom-
 * pan-pinch, shared via `DiagramViewer` with the fullscreen modal) and a
 * post-render contrast pass (`fixLabelContrastForHardcodedFills`) so
 * agent-hardcoded node fills stay legible in both themes.
 */
function MermaidDiagramImpl({ chart }: MermaidDiagramProps) {
  const { resolvedTheme } = useTheme();
  const id = useId().replace(/[:]/g, "-");
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false); // true once render() throws; source falls back to a code block
  const [fullscreen, setFullscreen] = useState(false); // whether the popup modal viewer is open

  useEffect(() => {
    // `cancelled` guards against a race where the chart/theme changes (and
    // this effect re-runs) before the previous render's async work finishes —
    // without it, a stale render could overwrite the SVG for the *new* props
    // after the fact.
    let cancelled = false;

    async function render() {
      setFailed(false);
      try {
        // Runtime `import()` (not a top-level `import mermaid from "mermaid"`)
        // — see this file's top-level doc comment for why: mermaid needs a
        // real DOM to render into and must never be pulled into the
        // server-side bundle/render.
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: resolvedTheme === "dark" ? "dark" : "default",
          securityLevel: "strict",
          fontFamily: "var(--font-sans-var), sans-serif",
          suppressErrorRendering: true, // stop mermaid from injecting its own error SVG into document.body on parse failure
        });
        // Unique id per render pass: the previous pass's svg can be in the DOM twice (inline card +
        // fullscreen modal), and mermaid.render() against an id that already exists collides with
        // those copies during its measurement phase, emitting corrupt markup (e.g. no viewBox).
        const { svg: rendered } = await mermaid.render(`mermaid-${id}-${Date.now()}`, chart);
        // Recolor labels sitting on hardcoded classDef/style fills so they stay legible (see helper doc comment above).
        const contrastFixed = fixLabelContrastForHardcodedFills(rendered);
        if (!cancelled) setSvg(contrastFixed);
      } catch (err) {
        // Parser error is noisy and not actionable for end users — keep it in the console for developers only.
        console.warn("Mermaid diagram failed to render:", err);
        if (!cancelled) setFailed(true);
      }
    }

    void render();
    return () => {
      cancelled = true;
    };
  }, [chart, resolvedTheme, id]);

  if (failed) {
    // Graceful fallback: show the raw source as a plain code block, styled like the loading state below.
    return (
      <div className="rounded-lg border border-border bg-muted/30 p-3">
        <p className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          Diagram couldn&apos;t render — showing source instead
        </p>
        <pre className="overflow-x-auto whitespace-pre text-xs">
          <code>{chart}</code>
        </pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-border bg-muted/30">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Rendering diagram" />
      </div>
    );
  }

  return (
    <>
      {/* Inline card: `overflow-hidden` (not overflow-x-auto) so the pan/zoom viewport clips instead of scrolling natively. */}
      <div className="my-4 overflow-hidden rounded-lg border border-border bg-card">
        {/* Inline viewer — the Maximize2 control opens the fullscreen modal below. */}
        <DiagramViewer svg={svg} chart={chart} onExpand={() => setFullscreen(true)} />
      </div>
      {/* Portal-rendered popup viewer; mounts a fresh DiagramViewer per open. */}
      <DiagramFullscreenModal open={fullscreen} onClose={() => setFullscreen(false)} svg={svg} chart={chart} />
    </>
  );
}

// memo: re-rendering itself restarts nothing (the effect above is deps-guarded),
// but this avoids pointless render work while the parent chat stream re-renders.
export const MermaidDiagram = memo(MermaidDiagramImpl);
