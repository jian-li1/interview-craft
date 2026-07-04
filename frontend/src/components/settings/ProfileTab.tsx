"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, Pencil } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { onboardingApi, ApiError } from "@/lib/api";
import type { ProfileOut } from "@/lib/types";

export function ProfileTab() {
  const [profile, setProfile] = useState<ProfileOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    onboardingApi
      .get()
      .then((p) => !cancelled && setProfile(p))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Failed to load profile"));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  if (!profile) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading profile…
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Background</CardTitle>
            <CardDescription>Your bio, experience, and goals.</CardDescription>
          </div>
          <Link href="/onboarding">
            <Button variant="outline" size="sm">
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              Edit background
            </Button>
          </Link>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div>
            <p className="text-xs font-medium text-muted-foreground">Bio</p>
            <p className="mt-0.5">{profile.bio || "—"}</p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Target roles</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {profile.target_roles.length > 0 ? (
                profile.target_roles.map((r) => <Badge key={r}>{r}</Badge>)
              ) : (
                <span>—</span>
              )}
            </div>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Skills</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {profile.skills.length > 0 ? (
                profile.skills.map((s) => (
                  <Badge key={s} variant="outline">
                    {s}
                  </Badge>
                ))
              ) : (
                <span>—</span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground">Experience level</p>
              <p className="mt-0.5 capitalize">{profile.experience_level.replace("_", " ")}</p>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Timeline</p>
              <p className="mt-0.5">{profile.timeline || "—"}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Synthesized profile</CardTitle>
          <CardDescription>What the agent remembers about you.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {profile.synthesized_profile || "Not generated yet — visit onboarding to create it."}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
