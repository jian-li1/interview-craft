"use client";

import { Loader2 } from "lucide-react";
import { useAuthGuard } from "@/components/auth/useAuthGuard";
import { AppShell } from "@/components/layout/AppShell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { ready } = useAuthGuard({ requireAuth: true, requireOnboarding: true });

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}
