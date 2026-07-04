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
  section: SectionOut;
  onExplain: (prompt: string) => void;
}

export function SectionContent({ section, onExplain }: SectionContentProps) {
  const components: Components = {
    code(props) {
      const { className, children, ...rest } = props;
      const match = /language-(\w+)/.exec(className ?? "");
      const raw = String(children).replace(/\n$/, "");

      if (match?.[1] === "mermaid") {
        return <MermaidDiagram chart={raw} />;
      }

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
      // react-markdown renders footnote refs as <a href="#fn...">; style them as superscript chips.
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
