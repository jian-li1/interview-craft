/**
 * Server-side auth fast-path for the App Router.
 *
 * This is a UX optimization ONLY — it exists to redirect unauthenticated/authenticated
 * visitors before any page renders, eliminating the flash-of-wrong-page that the
 * client-side `useAuthGuard` alone produces (guard runs after mount, so the wrong page
 * paints for a frame or two while the redirect kicks in). It is NOT the security
 * boundary: there's no JWT signature verification here (the frontend must never hold
 * the signing secret), so a forged cookie can sail through this middleware — it just
 * reaches the shell, where the client guard's `/api/auth/me` call and the backend's own
 * 401s/ownership checks are the actual gate. Real auth enforcement lives server-side in
 * FastAPI.
 */
import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";

// Only run this middleware on routes that care about auth state.
export const config = {
  matcher: ["/dashboard/:path*", "/settings/:path*", "/studio/:path*", "/onboarding", "/login"],
};

/**
 * Decodes the `ic_session` JWT's payload (2nd dot-segment) without verifying its
 * signature, and checks `exp` is still in the future. Returns false for any missing/
 * malformed cookie — decoding failures are treated as "no session" rather than errors.
 */
function hasValidSession(cookieValue: string | undefined): boolean {
  if (!cookieValue) return false;
  try {
    const payloadSegment = cookieValue.split(".")[1];
    if (!payloadSegment) return false;
    // JWTs use base64url; atob expects standard base64, so swap chars and re-pad.
    const base64 = payloadSegment.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const json = atob(padded);
    const payload = JSON.parse(json) as { exp?: number };
    // exp is in seconds since epoch; Date.now() is milliseconds.
    return typeof payload.exp === "number" && payload.exp * 1000 > Date.now();
  } catch {
    // Malformed base64/JSON — treat as no session rather than throwing.
    return false;
  }
}

export function middleware(request: NextRequest) {
  // Cross-origin Cloud Run topology: frontend and backend live on different *.run.app
  // hosts in production, so the (host-only) session cookie never reaches the Next
  // server there. Detecting that and passing through avoids a false "no session"
  // redirect loop with the client-side guard, which DOES see the cookie via the
  // browser's direct calls to the backend origin.
  const apiHostname = new URL(env.apiBaseUrl).hostname;
  if (request.nextUrl.hostname !== apiHostname) {
    return NextResponse.next();
  }

  const hasSession = hasValidSession(request.cookies.get("ic_session")?.value);
  const { pathname } = request.nextUrl;

  // /login: bounce already-authenticated visitors straight to the dashboard.
  if (pathname === "/login") {
    if (hasSession) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }
    return NextResponse.next();
  }

  // All other matched paths are protected — /dashboard, /settings, /studio, /onboarding.
  if (!hasSession) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return NextResponse.next();
}
