"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/Button";

/**
 * Light/dark theme toggle button. Reads/writes theme state via
 * `next-themes`' `useTheme()` (the store of record for the current theme,
 * provided by `ThemeProvider` higher in the tree) and flips between
 * "light" and "dark" based on `resolvedTheme` (the actual applied theme,
 * accounting for a "system" preference rather than the raw `theme` value).
 * Renders an empty placeholder of the same size until mounted, since
 * `resolvedTheme` is only accurate on the client post-hydration — rendering
 * the real icon before that would risk a server/client mismatch.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className={`h-9 w-9 ${className ?? ""}`} aria-hidden="true" />;
  }

  const isDark = resolvedTheme === "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={className}
    >
      {isDark ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
    </Button>
  );
}
