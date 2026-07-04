"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { ProfileTab } from "@/components/settings/ProfileTab";
import { PreferencesTab } from "@/components/settings/PreferencesTab";
import { AppearanceTab } from "@/components/settings/AppearanceTab";
import { AccountTab } from "@/components/settings/AccountTab";

/**
 * `/settings` — authenticated settings page, rendered inside the `(app)`
 * shell. Purely a tab-switcher shell: it owns no state of its own beyond
 * which tab is active (delegated entirely to the hand-rolled `Tabs`
 * primitive from `components/ui/Tabs`, defaulting to "profile"). Each of the
 * four tabs is a self-contained component under `components/settings/` that
 * fetches/mutates its own slice of settings:
 * - `ProfileTab` — the onboarding profile fields (bio, roles, skills, etc.).
 * - `PreferencesTab` — agent/LLM behavior preferences.
 * - `AppearanceTab` — theme/display preferences.
 * - `AccountTab` — account-level info/actions (e.g. sign out, danger zone).
 * `TabsContent` mounts/unmounts (or hides, per the `Tabs` primitive's
 * implementation) each panel based on the active `value`, matching the
 * `TabsTrigger` values above.
 */
export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6 lg:py-14">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <p className="mt-1.5 text-muted-foreground">
        Manage your profile, preferences, and account.
      </p>

      <Tabs defaultValue="profile" className="mt-8">
        <TabsList aria-label="Settings sections">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="appearance">Appearance</TabsTrigger>
          <TabsTrigger value="account">Account</TabsTrigger>
        </TabsList>

        <div className="mt-6">
          <TabsContent value="profile">
            <ProfileTab />
          </TabsContent>
          <TabsContent value="preferences">
            <PreferencesTab />
          </TabsContent>
          <TabsContent value="appearance">
            <AppearanceTab />
          </TabsContent>
          <TabsContent value="account">
            <AccountTab />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
