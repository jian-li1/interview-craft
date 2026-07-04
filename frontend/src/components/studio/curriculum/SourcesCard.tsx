import { ExternalLink } from "lucide-react";
import type { Citation } from "@/lib/types";

function faviconUrl(url: string): string | null {
  try {
    const { hostname } = new URL(url);
    return `https://www.google.com/s2/favicons?domain=${hostname}&sz=32`;
  } catch {
    return null;
  }
}

export function SourcesCard({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-8 rounded-xl border border-border bg-muted/30 p-4">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Sources
      </h4>
      <ul className="mt-3 space-y-2">
        {citations.map((c) => {
          const favicon = faviconUrl(c.url);
          return (
            <li key={c.id}>
              <a
                href={c.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-start gap-2.5 rounded-lg border border-transparent p-2 text-sm hover:border-border hover:bg-card"
              >
                <span
                  id={`fn-source-${c.id}`}
                  className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-accent"
                >
                  {c.id}
                </span>
                {favicon && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={favicon} alt="" className="mt-0.5 h-4 w-4 shrink-0 rounded-sm" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{c.title}</span>
                  <span className="block truncate text-xs text-muted-foreground">{c.url}</span>
                </span>
                <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
