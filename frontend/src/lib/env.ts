/**
 * Centralized, typed access to NEXT_PUBLIC_* environment variables.
 * Per spec 01 §4, only these three are exposed to the frontend:
 *  - `NEXT_PUBLIC_API_BASE_URL` — REST base URL for `apiFetch` (lib/api.ts).
 *    Defaults to `http://localhost:8000` (local backend dev server).
 *  - `NEXT_PUBLIC_WS_BASE_URL` — WebSocket base URL for `ChatSocket`
 *    (lib/ws.ts). Defaults to `ws://localhost:8000`.
 *  - `NEXT_PUBLIC_GOOGLE_CLIENT_ID` — Google Identity Services client id used
 *    by `GoogleSignInButton`. Defaults to `""` (empty), which effectively
 *    disables Google sign-in until the env var is configured.
 * Missing or empty values fall back to the defaults above rather than
 * throwing, so local dev works without a `.env.local` file.
 */

/** Returns `value` unless it's undefined/empty, in which case `fallback` is used. */
function readEnv(value: string | undefined, fallback: string): string {
  if (value === undefined || value === "") return fallback;
  return value;
}

// Next.js only inlines NEXT_PUBLIC_* vars into the client bundle when accessed
// as a static `process.env.VAR_NAME` expression — a dynamic `process.env[name]`
// lookup is never replaced and silently resolves to undefined in the browser.
export const env = {
  apiBaseUrl: readEnv(process.env.NEXT_PUBLIC_API_BASE_URL, "http://localhost:8000"),
  wsBaseUrl: readEnv(process.env.NEXT_PUBLIC_WS_BASE_URL, "ws://localhost:8000"),
  googleClientId: readEnv(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID, ""),
};
