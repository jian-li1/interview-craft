import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/layout/ThemeProvider";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { Toaster } from "sonner";

// Self-hosted Google font, exposed as a CSS variable (rather than a plain
// className) so it can be layered with the Tailwind `font-sans` utility
// applied on <body> below. `display: "swap"` avoids invisible-text flashes
// while the font loads.
const inter = Inter({
  variable: "--font-sans-var",
  subsets: ["latin"],
  display: "swap",
});

// Static <head> metadata for the whole app (App Router merges this into
// every page unless a route segment overrides it with its own `metadata`).
export const metadata: Metadata = {
  title: "InterviewCraft — Your AI interview-prep curriculum",
  description:
    "InterviewCraft generates comprehensive, personalized interview-preparation curricula through deep research, human-in-the-loop planning, and cited, visual lessons.",
};

// Viewport + theme-color config, split out from `metadata` per Next.js 15
// convention. The two `themeColor` entries let the browser chrome (e.g.
// mobile Safari's status bar) track the light/dark CSS custom properties
// defined in globals.css instead of requiring JS.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fafafa" },
    { media: "(prefers-color-scheme: dark)", color: "#09090b" },
  ],
};

/**
 * Root layout — wraps every route in the app (public pages, `/login`,
 * `/onboarding`, and the authenticated `(app)` route group alike).
 *
 * Provider ordering here is load-bearing:
 * 1. `ThemeProvider` (next-themes) must be outermost so it can set the
 *    `class` attribute on `<html>` before any themed descendant paints —
 *    `suppressHydrationWarning` on `<html>` is required alongside it because
 *    next-themes patches the class/style on the client after SSR, which
 *    would otherwise trigger a hydration mismatch warning.
 * 2. `AuthProvider` sits inside `ThemeProvider` and wraps `children`; it
 *    fetches `/api/auth/me` once and exposes the session via context, but
 *    does NOT itself gate rendering — per-route auth gating is done by
 *    `useAuthGuard` in individual layouts/pages (see `(app)/layout.tsx`).
 * 3. `Toaster` (sonner) is rendered as a sibling to `AuthProvider`'s subtree,
 *    inside `ThemeProvider`, so toast styling also follows the active theme.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`} suppressHydrationWarning>
      <body className="min-h-full flex flex-col font-sans">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <AuthProvider>{children}</AuthProvider>
          <Toaster richColors position="top-right" closeButton />
        </ThemeProvider>
      </body>
    </html>
  );
}
