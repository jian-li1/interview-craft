"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { ProfileTab } from "@/components/settings/ProfileTab";
import { AppearanceTab } from "@/components/settings/AppearanceTab";
import { AccountTab } from "@/components/settings/AccountTab";

/**
 * `/settings` — authenticated settings page, rendered inside the `(app)`
 * shell. Purely a tab-switcher shell: it owns no state of its own beyond
 * which tab is active (delegated entirely to the hand-rolled `Tabs`
 * primitive from `components/ui/Tabs`, defaulting to "profile"). Each of the
 * three tabs is a self-contained component under `components/settings/` that
 * fetches/mutates its own slice of settings:
 * - `ProfileTab` — the onboarding profile fields (bio, roles, skills, etc.).
 * - `AppearanceTab` — theme/display preferences.
 * - `AccountTab` — account-level info/actions (e.g. sign out, danger zone).
 * (LLM model / search provider selection moved out of here entirely — it's now
 * per-conversation via the chat composer's model/search chips, not a settings tab.)
 * All three `TabsContent` panels use `forceMount` so they stay mounted at once
 * (each tab's own data fetch runs in parallel on page load, and switching
 * tabs never re-triggers a fetch or shows a loading spinner); inactive
 * panels are hidden via the `hidden` attribute rather than unmounted,
 * matching the `TabsTrigger` values above.
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
          <TabsTrigger value="appearance">Appearance</TabsTrigger>
          <TabsTrigger value="account">Account</TabsTrigger>
        </TabsList>

        <div className="mt-6">
          {/* forceMount keeps all three panels mounted so their fetches fire in parallel and tab switches are instant */}
          <TabsContent value="profile" forceMount>
            <ProfileTab />
          </TabsContent>
          <TabsContent value="appearance" forceMount>
            <AppearanceTab />
          </TabsContent>
          <TabsContent value="account" forceMount>
            <AccountTab />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
