"use client";

import { useEffect, useRef, useState } from "react";
import { env } from "@/lib/env";
import { Loader2 } from "lucide-react";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
            ux_mode?: "popup" | "redirect";
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: Record<string, unknown>
          ) => void;
          prompt: () => void;
        };
      };
    };
  }
}

const SCRIPT_SRC = "https://accounts.google.com/gsi/client";

interface GoogleSignInButtonProps {
  onCredential: (idToken: string) => void;
  disabled?: boolean;
}

/**
 * Renders the official Google Identity Services (GIS) button. Loads the GIS
 * script on mount and calls `onCredential` with the raw ID token JWT.
 *
 * Integration flow (per the auth architecture in the root CLAUDE.md):
 * 1. This component loads `accounts.google.com/gsi/client` and renders the
 *    library's own button into `containerRef` (GIS controls the markup —
 *    we never build a custom sign-in button UI).
 * 2. On user interaction, GIS invokes the `callback` registered in
 *    `initialize()`, handing back a `credential` (the Google ID token JWT).
 * 3. This component forwards that raw ID token to the caller via
 *    `onCredential(idToken)` — it does NOT call the backend itself. The
 *    parent (e.g. the login page) is expected to pass the token to
 *    `authApi.loginWithGoogle`, which sends it to the backend for
 *    server-side verification (google-auth) and exchange for this app's own
 *    JWT, set as the httpOnly `ic_session` cookie.
 */
export function GoogleSignInButton({ onCredential, disabled }: GoogleSignInButtonProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const [scriptError, setScriptError] = useState(false);

  // Loads the GIS script exactly once (checks for an already-present <script>
  // tag first, e.g. from a prior mount), then flips scriptLoaded/scriptError
  // so the render effect below and the loading/error UI can react.
  useEffect(() => {
    if (window.google?.accounts?.id) {
      setScriptLoaded(true);
      return;
    }
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => setScriptLoaded(true));
      existing.addEventListener("error", () => setScriptError(true));
      return;
    }
    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => setScriptLoaded(true);
    script.onerror = () => setScriptError(true);
    document.head.appendChild(script);
  }, []);

  // Once the script is loaded (and we're not disabled), initialize the GIS
  // client with our OAuth client ID and register the credential callback,
  // then ask GIS to render its button into our container. Re-runs if
  // `disabled` or `onCredential` change so the registered callback always
  // closes over the latest prop.
  useEffect(() => {
    if (!scriptLoaded || !containerRef.current || !window.google || disabled) return;
    if (!env.googleClientId) return;

    window.google.accounts.id.initialize({
      client_id: env.googleClientId,
      // Step 2 of the flow described above: GIS calls this with the ID
      // token once the user completes sign-in via the rendered button.
      callback: (response) => onCredential(response.credential),
      ux_mode: "popup",
    });

    containerRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(containerRef.current, {
      type: "standard",
      theme: "outline",
      size: "large",
      shape: "pill",
      width: 320,
      text: "continue_with",
    });
  }, [scriptLoaded, disabled, onCredential]);

  if (!env.googleClientId) {
    return (
      <div className="rounded-lg border border-dashed border-warning/50 bg-warning/10 px-4 py-3 text-center text-xs text-warning">
        Set NEXT_PUBLIC_GOOGLE_CLIENT_ID to enable Google sign-in.
      </div>
    );
  }

  if (scriptError) {
    return (
      <div className="rounded-lg border border-dashed border-destructive/50 bg-destructive/10 px-4 py-3 text-center text-xs text-destructive">
        Couldn&apos;t load Google Sign-In. Check your connection and reload.
      </div>
    );
  }

  return (
    <div className="flex min-h-[44px] justify-center">
      {!scriptLoaded && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Loading Google sign-in" />}
      <div ref={containerRef} />
    </div>
  );
}
