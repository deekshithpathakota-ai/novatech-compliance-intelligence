/** Typed fetch wrapper. The token lives in memory + sessionStorage; the backend is always authoritative. */

/**
 * API origin. Empty in local dev (the Vite proxy forwards /api -> http://localhost:8000).
 * In production set VITE_API_URL to the backend origin, e.g. https://novatech-api.onrender.com.
 * Normalised so "https://x.com", "https://x.com/" and "https://x.com/api/" all produce https://x.com/api/... (never //api).
 */
export function normalizeApiBase(raw: string | undefined): string {
  let b = (raw ?? "").trim();
  if (!b) return "";
  b = b.replace(/\/+$/, "").replace(/\/api$/i, "").replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(b)) b = `https://${b}`; // tolerate "novatech-api.onrender.com"
  return b;
}
export const API_BASE = normalizeApiBase(import.meta.env.VITE_API_URL as string | undefined);
const BASE = API_BASE;
const apiUrl = (path: string) => `${BASE}${path.startsWith("/") ? path : `/${path}`}`;
const API_HOST = BASE ? BASE.replace(/^https?:\/\//, "") : "the API";

if (import.meta.env.PROD && !BASE) {
  console.warn("[novatech] VITE_API_URL is not set: API calls go to this site's own /api path. Set it to your backend origin and rebuild.");
}

/** Render's free tier sleeps; the first request after a pause can take ~50 s while the backend wakes up. */
const DEFAULT_TIMEOUT_MS = 70_000;
const UPLOAD_TIMEOUT_MS = 120_000;
const KEY = "nt-session";

let token: string | null = null;
try {
  token = sessionStorage.getItem(KEY);
} catch {
  token = null;
}

export function setToken(t: string | null) {
  token = t;
  try {
    if (t) sessionStorage.setItem(KEY, t);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable — keep in memory */
  }
}
export const getToken = () => token;

export type Why = { your_role?: string; required_permission?: string; resource?: string; recommended_action?: string };

export class ApiError extends Error {
  status: number;
  code: string;
  why?: Why;
  constructor(status: number, code: string, message: string, why?: Why) {
    super(message);
    this.status = status;
    this.code = code;
    this.why = why;
  }
}

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

/** Messages for responses that carry no JSON error body (proxies, cold starts, misrouted requests). */
function fallbackMessage(status: number): [string, string] {
  if (status === 401) return ["UNAUTHENTICATED", "Your session has expired. Please sign in again."];
  if (status === 403) return ["FORBIDDEN", "You don't have permission for this action."];
  if (status === 404) return ["NOT_FOUND", `The API endpoint was not found on ${API_HOST}. Check VITE_API_URL points at the backend.`];
  if (status === 405) return ["METHOD_NOT_ALLOWED", `The API rejected the request method. Check VITE_API_URL points at the backend, not the web app.`];
  if (status === 413) return ["TOO_LARGE", "The file is too large to upload."];
  if (status === 429) return ["RATE_LIMITED", "Too many requests. Please wait a moment."];
  if (status === 502 || status === 503 || status === 504)
    return ["BACKEND_UNAVAILABLE", "The backend is starting up or temporarily unavailable. Wait a few seconds and retry."];
  if (status >= 500) return ["SERVER_ERROR", "The server hit an unexpected error. No changes were recorded."];
  return ["ERROR", `Request failed (HTTP ${status}).`];
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), isForm ? UPLOAD_TIMEOUT_MS : DEFAULT_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (e) {
    if (ctrl.signal.aborted) throw new ApiError(0, "TIMEOUT", `${API_HOST} did not respond in time. If the backend was asleep it may now be awake — retry.`);
    if (typeof navigator !== "undefined" && navigator.onLine === false) throw new ApiError(0, "OFFLINE", "You appear to be offline. Check your connection.");
    if (import.meta.env.DEV) console.error("[novatech] network error", method, apiUrl(path), e);
    // A browser gives no detail for CORS blocks, DNS failures or a stopped server — name the likely causes.
    throw new ApiError(0, "NETWORK", BASE
      ? `Can't reach ${API_HOST}. The backend may be down, or CORS_ORIGINS on the backend doesn't include ${window.location.origin}.`
      : "Can't reach the NovaTech API. Check that the backend is running.");
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401 && path !== "/api/auth/login") {
    onUnauthorized?.();
  }
  const ct = res.headers.get("content-type") ?? "";
  if (!res.ok) {
    let detail: { code?: string; message?: string; why?: Why } = {};
    try {
      if (ct.includes("json")) detail = (await res.json()).detail ?? {};
    } catch {
      /* malformed JSON error body */
    }
    const [code, message] = fallbackMessage(res.status);
    throw new ApiError(res.status, detail.code ?? code, detail.message ?? message, detail.why);
  }
  if (ct.includes("text/html")) {
    // The SPA's index.html came back instead of JSON: requests are hitting the frontend host, not the API.
    throw new ApiError(0, "MISCONFIGURED", "The app received a web page instead of API data. Set VITE_API_URL to the backend URL and redeploy the frontend.");
  }
  return (ct.includes("application/json") ? res.json() : (res.blob() as unknown)) as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T,>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  upload: <T,>(p: string, form: FormData) => request<T>("POST", p, form, true),
};

export async function download(path: string, filename: string) {
  const blob = await request<Blob>("GET", path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Server-Sent Events over fetch (EventSource can't send the Authorization header). */
export async function streamRun(runId: number, onEvent: (event: string, data: any) => void, signal?: AbortSignal) {
  const res = await fetch(apiUrl(`/api/agent/runs/${runId}/stream`), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, "STREAM", "Live agent updates are unavailable.");
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    buf = buf.replace(/\r\n/g, "\n");
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx).replace(/\r/g, "");
      buf = buf.slice(idx + 2);
      const ev = /event: (.*)/.exec(chunk)?.[1] ?? "message";
      const data = /data: (.*)/s.exec(chunk)?.[1];
      if (data) onEvent(ev, JSON.parse(data));
    }
  }
}
