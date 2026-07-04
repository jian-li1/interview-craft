"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * Thin re-export wrapper around `next-themes`' `ThemeProvider`, forwarding
 * all props (e.g. `attribute="class"`, `defaultTheme`, `enableSystem`)
 * unchanged. `next-themes` is what actually handles dark/light theming here:
 * it toggles a class on `<html>` and injects a blocking inline script before
 * hydration so the correct theme class is applied on first paint — avoiding
 * the flash-of-wrong-theme/hydration-mismatch flicker that a purely
 * client-side (useEffect-driven) theme toggle would cause. This wrapper
 * exists only so the rest of the app can import a local, project-named
 * `ThemeProvider` from `@/components/layout` instead of `next-themes`
 * directly, and to keep the "use client" boundary co-located.
 */
export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
