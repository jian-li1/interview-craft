"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { ProfileTab } from "@/components/settings/ProfileTab";
import { PreferencesTab } from "@/components/settings/PreferencesTab";
import { AppearanceTab } from "@/components/settings/AppearanceTab";
import { AccountTab } from "@/components/settings/AccountTab";

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
