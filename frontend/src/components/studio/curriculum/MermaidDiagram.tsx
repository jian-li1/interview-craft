"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { AlertTriangle, Loader2 } from "lucide-react";

interface MermaidDiagramProps {
  /** Raw Mermaid diagram source (the fenced ```mermaid code block's contents), as extracted by SectionContent's custom `code` renderer. */
  chart: string;
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
 */
export function MermaidDiagram({ chart }: MermaidDiagramProps) {
  const { resolvedTheme } = useTheme();
  const id = useId().replace(/[:]/g, "-");
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // `cancelled` guards against a race where the chart/theme changes (and
    // this effect re-runs) before the previous render's async work finishes —
    // without it, a stale render could overwrite the SVG for the *new* props
    // after the fact.
    let cancelled = false;

    async function render() {
      setError(null);
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
        });
        const { svg: rendered } = await mermaid.render(`mermaid-${id}`, chart);
        if (!cancelled) setSvg(rendered);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to render diagram");
        }
      }
    }

    void render();
    return () => {
      cancelled = true;
    };
  }, [chart, resolvedTheme, id]);

  if (error) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
        <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
        <div>
          <p className="font-medium">Couldn&apos;t render diagram</p>
          <pre className="mt-1 whitespace-pre-wrap opacity-80">{error}</pre>
        </div>
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
    <div
      ref={containerRef}
      className="mermaid-container my-4 flex justify-center overflow-x-auto rounded-lg border border-border bg-card p-4"
      // eslint-disable-next-line react/no-danger -- mermaid's own sanitized SVG output, rendered in "strict" securityLevel
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
