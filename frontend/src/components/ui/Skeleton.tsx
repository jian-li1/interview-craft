import { cn } from "@/lib/utils";

/** Loading placeholder block with a shimmer animation (see the `shimmer` utility class). Size/shape controlled entirely via `className`. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("shimmer rounded-md", className)} aria-hidden="true" />;
}
