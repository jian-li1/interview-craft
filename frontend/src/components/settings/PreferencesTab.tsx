"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Select } from "@/components/ui/Select";
import { settingsApi, ApiError } from "@/lib/api";
import type { UserSettings } from "@/lib/types";
import { Loader2 } from "lucide-react";

export function PreferencesTab() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .get()
      .then((s) => !cancelled && setSettings(s))
      .catch(() => toast.error("Failed to load preferences"));
    return () => {
      cancelled = true;
    };
  }, []);

  async function save(next: Partial<UserSettings>) {
    if (!settings) return;
    const merged = { ...settings, ...next };
    setSettings(merged);
    setSaving(true);
    try {
      const updated = await settingsApi.update(next);
      setSettings(updated);
      toast.success("Preferences saved");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to save preferences");
    } finally {
      setSaving(false);
    }
  }

  if (!settings) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Loading preferences…
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Model preferences</CardTitle>
        <CardDescription>
          Choose which provider powers your agent, or leave it on the server default.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div>
          <label htmlFor="llm-provider" className="text-sm font-medium">
            LLM provider
          </label>
          <div className="mt-1.5 max-w-xs">
            <Select
              id="llm-provider"
              value={settings.llm_provider ?? ""}
              onChange={(e) => save({ llm_provider: e.target.value || null })}
              disabled={saving}
            >
              <option value="">Server default</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
              <option value="llamacpp">llama.cpp (local, OpenAI-compatible)</option>
            </Select>
          </div>
        </div>
        <div>
          <label htmlFor="search-provider" className="text-sm font-medium">
            Search provider
          </label>
          <div className="mt-1.5 max-w-xs">
            <Select
              id="search-provider"
              value={settings.search_provider ?? ""}
              onChange={(e) => save({ search_provider: e.target.value || null })}
              disabled={saving}
            >
              <option value="">Server default</option>
              <option value="duckduckgo">DuckDuckGo</option>
              <option value="google">Google</option>
              <option value="tavily">Tavily</option>
            </Select>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
