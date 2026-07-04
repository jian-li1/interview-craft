"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LayoutGrid, PlusCircle, Settings, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/settings", label: "Settings", icon: Settings },
];

/**
 * Primary navigation for the authenticated shell: logo/home link, a
 * "New curriculum" button (routes to `/dashboard`, where the prompt box
 * lives), and nav links (`navItems`: Dashboard, Settings) with active-route
 * highlighting via `usePathname()` compared against each `item.href`
 * (exact match, styled through `cn()`). `onNavigate` is supplied by
 * `AppShell` when this is rendered inside the mobile drawer, so link/button
 * clicks can also close the drawer.
 */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();

  function handleNewCurriculum() {
    onNavigate?.();
    router.push("/dashboard");
  }

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <Link href="/dashboard" className="flex items-center gap-2 px-2 py-1 font-semibold">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-accent text-white">
          <Sparkles className="h-4 w-4" aria-hidden="true" />
        </span>
        InterviewCraft
      </Link>

      <button
        type="button"
        onClick={handleNewCurriculum}
        className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition-opacity hover:opacity-90"
      >
        <PlusCircle className="h-4 w-4" aria-hidden="true" />
        New curriculum
      </button>

      <nav className="flex flex-col gap-1" aria-label="Main navigation">
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-accent-soft text-accent"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <item.icon className="h-4 w-4" aria-hidden="true" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto rounded-lg border border-dashed border-border p-3 text-xs text-muted-foreground">
        Tip: describe the role, company, and timeline for the most tailored curriculum.
      </div>
    </div>
  );
}

/** Close ("X") button shown at the top of the mobile sidebar drawer in `AppShell`. */
export function MobileSidebarClose({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="Close navigation"
      className="absolute right-3 top-3 rounded-md p-1.5 hover:bg-muted"
    >
      <X className="h-5 w-5" aria-hidden="true" />
    </button>
  );
}
