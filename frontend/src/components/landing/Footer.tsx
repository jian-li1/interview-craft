import Link from "next/link";
import { Sparkles } from "lucide-react";

/** Landing page section: site footer with the logo/home link and copyright line. */
export function Footer() {
  return (
    <footer className="px-4 py-10 sm:px-6">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 border-t border-border/60 pt-8 sm:flex-row">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-accent text-white">
            <Sparkles className="h-3 w-3" aria-hidden="true" />
          </span>
          InterviewCraft
        </Link>
        <p className="text-xs text-muted-foreground">
          &copy; {new Date().getFullYear()} InterviewCraft. All rights reserved.
        </p>
      </div>
    </footer>
  );
}
