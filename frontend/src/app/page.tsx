import { PublicNavbar } from "@/components/layout/PublicNavbar";
import { Hero } from "@/components/landing/Hero";
import { Features } from "@/components/landing/Features";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Footer } from "@/components/landing/Footer";

/**
 * Public marketing/landing page served at `/`.
 *
 * Fully static and public — it lives outside the `(app)` route group, so it
 * does not run `useAuthGuard` and renders identically for signed-in and
 * signed-out visitors (no data fetching, no session check). Composes the
 * marketing sections (`Hero`, `Features`, `HowItWorks`) between the public
 * navbar and footer; `PublicNavbar` is responsible for surfacing sign-in/
 * dashboard links based on auth state itself.
 */
export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <PublicNavbar />
      <main className="flex-1">
        <Hero />
        <Features />
        <HowItWorks />
      </main>
      <Footer />
    </div>
  );
}
