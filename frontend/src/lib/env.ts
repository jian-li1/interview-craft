/**
 * Centralized, typed access to NEXT_PUBLIC_* environment variables.
 * Per spec 01 §4, only these three are exposed to the frontend.
 */

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
