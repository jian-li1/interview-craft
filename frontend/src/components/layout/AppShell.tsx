"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Menu, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Sidebar, MobileSidebarClose } from "@/components/layout/Sidebar";
import { UserMenu } from "@/components/layout/UserMenu";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { cn } from "@/lib/utils";

// Persists whether the desktop sidebar is expanded across visits.
const SIDEBAR_OPEN_STORAGE_KEY = "ic:sidebar-open";
const SIDEBAR_WIDTH = 256;

/**
 * The authenticated app shell: composes a persistent `Sidebar` (as a static,
 * collapsible column on desktop, a slide-in drawer on mobile) with a header
 * (desktop collapse toggle, mobile menu button, `ThemeToggle`, `UserMenu`)
 * and a scrollable main content area for `children`. Rendered by the `(app)`
 * route group's `layout.tsx` after
 * `useAuthGuard({requireAuth:true, requireOnboarding:true})` passes, so
 * every page nested here can assume an authenticated, onboarded user.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  // Desktop sidebar collapse state; defaults to open, then synced from
  // localStorage in an effect (not the initializer) to avoid an SSR/client
  // hydration mismatch — this component renders on the server first.
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    const stored = window.localStorage.getItem(SIDEBAR_OPEN_STORAGE_KEY);
    if (stored !== null) setSidebarOpen(stored === "true");
  }, []);

  // Toggle + persist in one place so every caller stays in sync with storage.
  const toggleSidebar = () => {
    setSidebarOpen((prev) => {
      const next = !prev;
      window.localStorage.setItem(SIDEBAR_OPEN_STORAGE_KEY, String(next));
      return next;
    });
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Desktop sidebar: animates width to collapse/expand, border drops when closed. */}
      <motion.aside
        animate={{ width: sidebarOpen ? SIDEBAR_WIDTH : 0 }}
        transition={{ type: "tween", duration: 0.2 }}
        className={cn(
          "hidden shrink-0 overflow-hidden md:block",
          sidebarOpen && "border-r border-border"
        )}
      >
        {/* Fixed-width inner wrapper so Sidebar content doesn't reflow while animating. */}
        <div className="w-64">
          <Sidebar />
        </div>
      </motion.aside>

      {/* Mobile sidebar drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-black/40 md:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileOpen(false)}
            />
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "tween", duration: 0.2 }}
              className="fixed inset-y-0 left-0 z-50 w-72 border-r border-border bg-card md:hidden"
            >
              <MobileSidebarClose onClose={() => setMobileOpen(false)} />
              <Sidebar onNavigate={() => setMobileOpen(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            className="rounded-md p-1.5 hover:bg-muted md:hidden"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </button>
          {/* Desktop-only sidebar collapse toggle, mirrors the mobile menu button's style. */}
          <button
            type="button"
            onClick={toggleSidebar}
            aria-label={sidebarOpen ? "Hide navigation" : "Show navigation"}
            className="hidden rounded-md p-1.5 hover:bg-muted md:block"
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-5 w-5" aria-hidden="true" />
            ) : (
              <PanelLeftOpen className="h-5 w-5" aria-hidden="true" />
            )}
          </button>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
