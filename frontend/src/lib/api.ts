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

function extractMessage(body: ApiErrorBody | null, fallback: string): string {
  if (!body) return fallback;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    return body.detail.map((d) => d.msg).join("; ");
  }
  if (body.message) return body.message;
  return fallback;
}

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

export const settingsApi = {
  get: () => apiFetch<UserSettings>("/api/settings"),
  update: (payload: SettingsUpdateRequest) =>
    apiFetch<UserSettings>("/api/settings", { method: "PUT", body: payload }),
};

export const healthApi = {
  check: () => apiFetch<{ status: string }>("/api/healthz", { skipAuthRedirect: true }),
};
