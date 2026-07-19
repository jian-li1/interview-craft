"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut, Settings, ChevronDown, LayoutDashboard } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useAuthStore } from "@/stores/useAuthStore";
import { initials } from "@/lib/utils";
import { toast } from "sonner";

/**
 * Account dropdown menu: avatar (Google profile picture, falling back to
 * initials) plus name, expanding into a popover with a log out action.
 * Renders nothing if `useAuthStore` has no `user` yet (e.g. before
 * `AuthProvider`'s initial fetch resolves).
 *
 * Two usages via the `variant` prop:
 * - `"app"` (default) — shown in `AppShell`'s header; dropdown has a
 *   Settings link (`/settings`) above Log out.
 * - `"landing"` — shown in `PublicNavbar` for signed-in visitors; dropdown
 *   swaps Settings for a "Go to dashboard" link (`/dashboard`) as the first
 *   item, since Settings isn't a relevant action from the public landing page.
 */
export function UserMenu({ variant = "app" }: { variant?: "app" | "landing" }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // Closes the dropdown when the user clicks anywhere outside its container.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  if (!user) return null;

  // Calls the auth store's logout (which clears the ic_session cookie
  // server-side via authApi.logout) then redirects to /login.
  async function handleLogout() {
    try {
      await logout();
      toast.success("Signed out");
      router.push("/login");
    } catch {
      toast.error("Failed to sign out. Please try again.");
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Open account menu"
        className="flex items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-accent-soft text-xs font-semibold text-accent">
          {user.picture ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={user.picture} alt="" className="h-full w-full object-cover" />
          ) : (
            initials(user.name)
          )}
        </span>
        <span className="hidden max-w-[8rem] truncate text-sm font-medium sm:inline">
          {user.name}
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
          >
            <div className="border-b border-border px-3 py-2.5">
              <p className="truncate text-sm font-medium">{user.name}</p>
              <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            </div>
            {variant === "landing" ? (
              // Landing variant: dashboard shortcut replaces Settings (not relevant off the public page).
              <Link
                href="/dashboard"
                role="menuitem"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
              >
                <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
                Go to dashboard
              </Link>
            ) : (
              <Link
                href="/settings"
                role="menuitem"
                onClick={() => setOpen(false)}
                className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted"
              >
                <Settings className="h-4 w-4" aria-hidden="true" />
                Settings
              </Link>
            )}
            <button
              type="button"
              role="menuitem"
              onClick={handleLogout}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-destructive hover:bg-destructive/10"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Log out
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
