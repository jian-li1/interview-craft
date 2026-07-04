"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LayoutGrid, PlusCircle, Settings, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { conversationsApi } from "@/lib/api";
import { toast } from "sonner";
import { useState } from "react";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const [creating, setCreating] = useState(false);

  async function handleNewCurriculum() {
    setCreating(true);
    try {
      const { conversation_id } = await conversationsApi.create({ curriculum_prompt: null });
      onNavigate?.();
      router.push(`/studio/${conversation_id}`);
    } catch {
      toast.error("Couldn't start a new curriculum. Please try again.");
    } finally {
      setCreating(false);
    }
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
        disabled={creating}
        className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition-opacity hover:opacity-90 disabled:opacity-60"
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
