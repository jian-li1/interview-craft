"use client";

import { useEffect, useState } from "react";

const MOBILE_BREAKPOINT_QUERY = "(max-width: 767px)";

/**
 * Tracks whether the viewport matches Tailwind's `md` breakpoint cutoff
 * (< 768px). Returns `null` until mounted client-side so callers can avoid
 * flashing the wrong layout during hydration.
 */
export function useIsMobile(): boolean | null {
  const [isMobile, setIsMobile] = useState<boolean | null>(null);

  useEffect(() => {
    // matchMedia (not window.innerWidth + a resize listener) so the browser
    // handles the threshold check natively and we only re-render on actual
    // crossings of the breakpoint, not on every resize event.
    const mql = window.matchMedia(MOBILE_BREAKPOINT_QUERY);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return isMobile;
}
