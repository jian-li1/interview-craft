"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { LogOut } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/components/auth/AuthProvider";
import { useAuthStore } from "@/stores/useAuthStore";

export function AccountTab() {
  const { user } = useAuth();
  const logout = useAuthStore((s) => s.logout);
  const router = useRouter();

  async function handleLogout() {
    try {
      await logout();
      toast.success("Signed out");
      router.push("/login");
    } catch {
      toast.error("Failed to sign out");
    }
  }

  if (!user) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>Manage your session.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div>
          <p className="text-xs font-medium text-muted-foreground">Email</p>
          <p className="mt-0.5 text-sm">{user.email}</p>
        </div>
        <Button variant="destructive" size="sm" onClick={handleLogout}>
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Log out
        </Button>
      </CardContent>
    </Card>
  );
}
