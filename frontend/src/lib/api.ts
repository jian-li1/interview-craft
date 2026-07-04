import { env } from "@/lib/env";
import type {
  ApiErrorBody,
  ConversationSummary,
  CreateConversationRequest,
  CreateConversationResponse,
  CurriculumFull,
  CurriculumSummary,
  MessageOut,
  OkResponse,
  PlanOut,
  ProfileIn,
  ProfileOut,
  ResumeUploadResponse,
  SettingsUpdateRequest,
  SynthesizeResponse,
  UserOut,
  UserSettings,
} from "@/lib/types";

/**
 * Typed error thrown by `apiFetch` whenever the backend responds with a
 * non-2xx status. Carries the parsed body (if JSON) and the HTTP status.
 */
export class ApiError extends Error {
  status: number;
  body: ApiErrorBody | null;

  constructor(status: number, message: string, body: ApiErrorBody | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip the automatic redirect-to-/login on 401 (used by the auth guard itself). */
  skipAuthRedirect?: boolean;
  /** Pass a FormData body verbatim (no JSON stringify / content-type header). */
  isFormData?: boolean;
}

/**
 * Pulls a human-readable message out of a backend error body. FastAPI's
 * validation errors arrive as `detail: {msg, loc}[]` (422s), plain-string
 * `detail` covers most hand-raised HTTPExceptions, and `message` is a
 * fallback for any non-FastAPI error shape. Falls back to `fallback` (e.g.
 * `res.statusText`) if none of those are present.
 */
function extractMessage(body: ApiErrorBody | null, fallback: string): string {
  if (!body) return fallback;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    return body.detail.map((d) => d.msg).join("; ");
  }
  if (body.message) return body.message;
  return fallback;
}

/** True for HTTP methods that mutate state — used to gate the CSRF header. */
function isMutatingMethod(method: string): boolean {
  return ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
}

/**
 * Typed fetch wrapper per spec 03 §4:
 * - credentials: "include" (session cookie)
 * - X-Requested-With header on mutating requests (CSRF mitigation)
 * - JSON errors surfaced as ApiError
 * - 401 -> redirect to /login (unless explicitly skipped)
 */
export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const { body, skipAuthRedirect, isFormData, headers, method = "GET", ...rest } = options;

  const finalHeaders = new Headers(headers);
  if (isMutatingMethod(method)) {
    finalHeaders.set("X-Requested-With", "XMLHttpRequest");
  }
  let finalBody: BodyInit | undefined;
  if (isFormData && body instanceof FormData) {
    finalBody = body;
  } else if (body !== undefined) {
    finalHeaders.set("Content-Type", "application/json");
    finalBody = JSON.stringify(body);
  }

  const url = path.startsWith("http") ? path : `${env.apiBaseUrl}${path}`;

  let res: Response;
  try {
    res = await fetch(url, {
      ...rest,
      method,
      headers: finalHeaders,
      credentials: "include",
      body: finalBody,
    });
  } catch (err) {
    throw new ApiError(0, "Network error — could not reach the server.", null);
  }

  if (res.status === 401 && !skipAuthRedirect) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Not authenticated", null);
  }

  const contentType = res.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const parsed = isJson ? await res.json().catch(() => null) : null;

  if (!res.ok) {
    const message = extractMessage(parsed, res.statusText || "Request failed");
    throw new ApiError(res.status, message, parsed);
  }

  return parsed as T;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/**
 * Wraps `/api/auth/*` — Google Identity Services login, logout, and the
 * "who am I" check. `me()` is called both by `AuthProvider` on mount (where
 * a 401 is expected/normal for logged-out users, hence `skipAuthRedirect`)
 * and by the auth guard, which wants the default redirect-to-/login behavior.
 */
export const authApi = {
  loginWithGoogle: (idToken: string) =>
    apiFetch<UserOut>("/api/auth/google", {
      method: "POST",
      body: { id_token: idToken },
    }),
  logout: () => apiFetch<OkResponse>("/api/auth/logout", { method: "POST" }),
  me: (skipAuthRedirect = false) =>
    apiFetch<UserOut>("/api/auth/me", { skipAuthRedirect }),
};

// ---------------------------------------------------------------------------
// Onboarding
// ---------------------------------------------------------------------------

/**
 * Wraps `/api/onboarding` — the user profile that feeds curriculum
 * personalization (bio, background, goals, resume text, synthesized
 * profile). `uploadResume` wraps the file in `FormData` and sets
 * `isFormData: true` so `apiFetch` sends it verbatim instead of
 * JSON-stringifying it (no `Content-Type` header is set, letting the
 * browser attach the correct multipart boundary). `synthesize` triggers the
 * backend to LLM-summarize the raw profile fields into `synthesized_profile`.
 */
export const onboardingApi = {
  get: () => apiFetch<ProfileOut>("/api/onboarding"),
  update: (profile: ProfileIn) =>
    apiFetch<ProfileOut>("/api/onboarding", { method: "PUT", body: profile }),
  uploadResume: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<ResumeUploadResponse>("/api/onboarding/resume", {
      method: "POST",
      body: form,
      isFormData: true,
    });
  },
  synthesize: () =>
    apiFetch<SynthesizeResponse>("/api/onboarding/synthesize", { method: "POST" }),
};

// ---------------------------------------------------------------------------
// Curricula
// ---------------------------------------------------------------------------

/**
 * Wraps `/api/curricula` — the generated curricula themselves (list/detail
 * for the dashboard and reader, delete, and the proposed task plan used by
 * the HITL plan-approval flow). `get` returns the full nested
 * modules/sections tree (`CurriculumFull`); `list` returns lightweight
 * summaries for the dashboard grid.
 */
export const curriculaApi = {
  list: () => apiFetch<CurriculumSummary[]>("/api/curricula"),
  get: (id: string) => apiFetch<CurriculumFull>(`/api/curricula/${id}`),
  remove: (id: string) =>
    apiFetch<OkResponse>(`/api/curricula/${id}`, { method: "DELETE" }),
  plan: (id: string) => apiFetch<PlanOut>(`/api/curricula/${id}/plan`),
};

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------

/**
 * Wraps `/api/conversations` — the chat threads that drive curriculum
 * generation via the agent. `create` starts a new conversation (optionally
 * seeded with an initial `curriculum_prompt`) and returns the id used to open
 * the chat WebSocket (see `ChatSocket` in `lib/ws.ts`). `messages` fetches
 * persisted history for hydrating the store on load
 * (`useChatStore.hydrateHistory`).
 */
export const conversationsApi = {
  list: () => apiFetch<ConversationSummary[]>("/api/conversations"),
  create: (payload: CreateConversationRequest) =>
    apiFetch<CreateConversationResponse>("/api/conversations", {
      method: "POST",
      body: payload,
    }),
  messages: (id: string) =>
    apiFetch<MessageOut[]>(`/api/conversations/${id}/messages`),
};

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

/**
 * Wraps `/api/settings` — user-level preferences (theme, LLM/search provider
 * overrides) that are persisted server-side and synced across devices.
 */
export const settingsApi = {
  get: () => apiFetch<UserSettings>("/api/settings"),
  update: (payload: SettingsUpdateRequest) =>
    apiFetch<UserSettings>("/api/settings", { method: "PUT", body: payload }),
};

/**
 * Wraps `/api/healthz` — a liveness probe. Always passes
 * `skipAuthRedirect: true` since this endpoint is unauthenticated and a 401
 * here should never bounce the user to `/login`.
 */
export const healthApi = {
  check: () => apiFetch<{ status: string }>("/api/healthz", { skipAuthRedirect: true }),
};
