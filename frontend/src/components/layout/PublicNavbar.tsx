"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ThemeToggle } from "@/components/layout/ThemeToggle";

export function PublicNavbar() {
  const router = useRouter();
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-accent text-white">
            <Sparkles className="h-4 w-4" aria-hidden="true" />
          </span>
          <span>InterviewCraft</span>
        </Link>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={() => router.push("/login")}>
            Log in
          </Button>
          <Button size="sm" onClick={() => router.push("/login")}>
            Get started
          </Button>
        </div>
      </nav>
    </header>
  );
}
