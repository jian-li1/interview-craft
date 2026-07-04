"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import type { Components } from "react-markdown";
import { MessageCircleQuestionMark } from "lucide-react";
import { MermaidDiagram } from "@/components/studio/curriculum/MermaidDiagram";
import { SourcesCard } from "@/components/studio/curriculum/SourcesCard";
import type { SectionOut } from "@/lib/types";

interface SectionContentProps {
  /** One written section, including its markdown body and citations array (per root CLAUDE.md: "sections cite [^n] footnotes mirrored in a citations array"). */
  section: SectionOut;
  /** Called with a canned "explain this in simpler terms" prompt when the user clicks the inline help icon next to an h2 heading; wired up to prefill the chat composer (see ChatPanel's prefillText). */
  onExplain: (prompt: string) => void;
}

/**
 * Renders one section's `content_markdown` via react-markdown (GFM +
 * rehype-highlight for code blocks), with custom component overrides for:
 *  - `code` — fenced ```mermaid blocks are diverted to `MermaidDiagram`
 *    instead of being rendered as a literal code block; everything else
 *    (inline code and other fenced blocks) renders normally.
 *  - `h2` — every H2 gets a small "explain this" affordance next to it
 *    that calls `onExplain` with a canned prompt referencing the heading text.
 *  - `a` — react-markdown's remark-gfm footnote support renders footnote
 *    reference links as `<a href="#fn...">`; those are re-styled here as
 *    small superscript numbered chips (matching the `[^n]` citation markers
 *    described in root CLAUDE.md), while ordinary links get
 *    target="_blank"/rel="noopener noreferrer" instead.
 * `SourcesCard` is rendered below the markdown body and lists `section.citations`
 * — the same citations that the footnote chips link down to.
 */
export function SectionContent({ section, onExplain }: SectionContentProps) {
  const components: Components = {
    code(props) {
      const { className, children, ...rest } = props;
      const match = /language-(\w+)/.exec(className ?? "");
      const raw = String(children).replace(/\n$/, "");

      // Fenced code blocks tagged ```mermaid are diagrams, not literal code —
      // hand them off to MermaidDiagram (which itself defers the actual
      // mermaid import to a client-side-only useEffect; see that file).
      if (match?.[1] === "mermaid") {
        return <MermaidDiagram chart={raw} />;
      }

      // NOTE: both branches below render identically (`<code className rest>`)
      // — `isBlock` is computed but doesn't currently change the output. Left
      // as-is per doc-only-pass scope; flagged in the task report rather than
      // "fixed" here.
      const isBlock = Boolean(match) || raw.includes("\n");
      if (!isBlock) {
        return (
          <code className={className} {...rest}>
            {children}
          </code>
        );
      }

      return (
        <code className={className} {...rest}>
          {children}
        </code>
      );
    },
    h2({ children, ...rest }) {
      const text = String(children);
      return (
        <div className="group relative flex items-center gap-1.5">
          <h2 {...rest}>{children}</h2>
          <button
            type="button"
            onClick={() => onExplain(`Explain "${text}" in simpler terms`)}
            aria-label={`Explain "${text}" in simpler terms`}
            className="flex shrink-0 items-center justify-center rounded-full p-1 text-muted-foreground/50 transition-colors hover:bg-muted hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:text-muted-foreground"
          >
            <MessageCircleQuestionMark className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      );
    },
    a({ children, href, ...rest }) {
      // react-markdown (via remark-gfm) renders markdown footnote refs
      // (e.g. `text[^3]`) as <a href="#fn-3"> or, with the
      // remark-rehype "clobber prefix" option, `#user-content-fn-3` — check
      // both forms so the `[^n]` citation markers described in root
      // CLAUDE.md are reliably detected and styled as chips regardless of
      // which prefix react-markdown's pipeline happens to produce.
      const isFootnoteRef = href?.startsWith("#user-content-fn-") || href?.startsWith("#fn-");
      if (isFootnoteRef) {
        return (
          <a
            href={href}
            {...rest}
            className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-soft px-1 text-[10px] font-semibold text-accent no-underline align-super"
          >
            {children}
          </a>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
          {children}
        </a>
      );
    },
  };

  return (
    <div>
      <div className="prose-reader">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeHighlight]}
          components={components}
        >
          {section.content_markdown}
        </ReactMarkdown>
      </div>
      <SourcesCard citations={section.citations} />
    </div>
  );
}
