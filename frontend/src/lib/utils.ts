import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merges conditional/variadic className inputs (arrays, objects, falsy
 * values — anything `clsx` accepts) and then resolves conflicting Tailwind
 * utility classes via `tailwind-merge` (e.g. `cn("p-2", cond && "p-4")`
 * correctly keeps only `p-4` instead of emitting both). Use this everywhere
 * instead of hand-concatenating className strings.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Format an ISO date string as a relative "time ago" label. */
export function timeAgo(iso: string): string {
  const date = new Date(iso);
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (Number.isNaN(seconds)) return "";
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(months / 12);
  return `${years}y ago`;
}

/** Format milliseconds as a short human duration, e.g. "1.2s" or "340ms". */
export function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Derives up to a two-letter avatar initials string from a display name,
 * e.g. "Jane Doe" -> "JD". Collapses repeated spaces (via `filter(Boolean)`
 * on the split), takes at most the first two words, and returns "" for an
 * empty/whitespace-only name.
 */
export function initials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}
