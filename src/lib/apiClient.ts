/**
 * Central API client — single source for backend URL and fetch behavior.
 * Operator secrets must never use NEXT_PUBLIC_* — see apiPostOperator + /operator-proxy.
 */

import { getSessionOperatorToken } from "@/lib/operatorAuth";

export type ApiFetchResult<T> = {
  ok: boolean;
  status: number;
  url: string;
  data: T | null;
  error: string | null;
  contentType: string | null;
  rawKeys: string[];
  corsBlocked?: boolean;
  timedOut?: boolean;
  degraded?: boolean;
};

/** Default page/card fetch budget — never block UI for 45s. */
export const API_TIMEOUT_MS = 3000;
export const CARD_TIMEOUT_MS = 2000;
export const DIAGNOSTIC_POLL_MS = 2500;

const PRODUCTION_BACKEND_DEFAULT = "https://hive-production-7343.up.railway.app";

/**
 * Server-side: absolute backend URL (SSR, rewrites target).
 * Browser: relative /api/* so Next.js rewrites proxy to backend (avoids CORS).
 */
export function getApiBaseUrl(options?: { forServer?: boolean }): string {
  const forServer = options?.forServer ?? typeof window === "undefined";

  if (!forServer) {
    return "";
  }

  const fromEnv =
    process.env.API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.VITE_API_BASE_URL;

  if (fromEnv?.trim()) {
    return fromEnv.replace(/\/$/, "");
  }

  return PRODUCTION_BACKEND_DEFAULT;
}

function sessionOperatorHeaders(): Record<string, string> {
  const token = getSessionOperatorToken();
  if (!token) return {};
  return { "X-Operator-Token": token };
}

export function buildApiUrl(path: string, forServer?: boolean): string {
  const base = getApiBaseUrl({ forServer });
  const p = path.startsWith("/") ? path : `/${path}`;
  if (!base) return p;
  return `${base}${p}`;
}

function keysOf(json: unknown): string[] {
  if (json && typeof json === "object" && !Array.isArray(json)) {
    return Object.keys(json as Record<string, unknown>);
  }
  return [];
}

export async function apiGet<T = unknown>(
  path: string,
  options?: { forServer?: boolean; signal?: AbortSignal; timeoutMs?: number }
): Promise<ApiFetchResult<T>> {
  const url = buildApiUrl(path, options?.forServer);
  const timeoutMs = options?.timeoutMs ?? API_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const signal = options?.signal ?? controller.signal;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
    clearTimeout(timer);
    const contentType = res.headers.get("content-type");
    let data: T | null = null;
    let error: string | null = null;
    const text = await res.text();
    if (contentType?.includes("application/json") && text) {
      try {
        data = JSON.parse(text) as T;
      } catch {
        error = `Invalid JSON from ${path}`;
      }
    } else if (!res.ok) {
      error = text.slice(0, 200) || res.statusText;
    } else if (text) {
      try {
        data = JSON.parse(text) as T;
      } catch {
        data = text as unknown as T;
      }
    }
    if (!res.ok && !error) {
      const errBody = data as { message?: string; detail?: string } | null;
      error = errBody?.message || errBody?.detail || res.statusText || `HTTP ${res.status}`;
    }
    return {
      ok: res.ok,
      status: res.status,
      url,
      data,
      error: res.ok ? null : error,
      contentType,
      rawKeys: keysOf(data),
    };
  } catch (e) {
    clearTimeout(timer);
    const msg = e instanceof Error ? e.message : String(e);
    const timedOut = msg.includes("abort") || msg.includes("Abort");
    const corsBlocked =
      typeof window !== "undefined" &&
      (msg.includes("Failed to fetch") || msg.includes("NetworkError"));
    return {
      ok: false,
      status: 0,
      url,
      data: null,
      error: timedOut
        ? `Data temporarily unavailable — using last snapshot (${timeoutMs}ms)`
        : corsBlocked
          ? `CORS or network blocked: ${msg} (called ${url})`
          : msg,
      contentType: null,
      rawKeys: [],
      corsBlocked,
      timedOut,
      degraded: timedOut,
    };
  }
}

/** Safe POST — no operator auth (read-only maintenance like resync). */
export async function apiPost<T = unknown>(
  path: string,
  body?: unknown,
  options?: { forServer?: boolean }
): Promise<ApiFetchResult<T>> {
  const url = buildApiUrl(path, options?.forServer);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
    const contentType = res.headers.get("content-type");
    const text = await res.text();
    let data: T | null = null;
    if (text && contentType?.includes("json")) {
      data = JSON.parse(text) as T;
    }
    return {
      ok: res.ok,
      status: res.status,
      url,
      data,
      error: res.ok ? null : (text.slice(0, 200) || res.statusText),
      contentType,
      rawKeys: keysOf(data),
    };
  } catch (e) {
    return {
      ok: false,
      status: 0,
      url,
      data: null,
      error: e instanceof Error ? e.message : String(e),
      contentType: null,
      rawKeys: [],
    };
  }
}

let serverProxyAvailable: boolean | null = null;

export async function checkServerOperatorProxy(): Promise<boolean> {
  if (typeof window === "undefined") return Boolean(process.env.OPERATOR_SECRET?.trim());
  if (serverProxyAvailable !== null) return serverProxyAvailable;
  try {
    const res = await fetch("/operator-proxy", { cache: "no-store" });
    const data = (await res.json()) as { server_operator_auth_configured?: boolean };
    serverProxyAvailable = Boolean(data.server_operator_auth_configured);
  } catch {
    serverProxyAvailable = false;
  }
  return serverProxyAvailable;
}

/** Mutating POST via server proxy or operator session token (never NEXT_PUBLIC). */
export async function apiPostOperator<T = unknown>(
  backendPath: string,
  body?: unknown
): Promise<ApiFetchResult<T> & { authMode?: string }> {
  const proxyOk = await checkServerOperatorProxy();
  if (proxyOk) {
    const res = await fetch("/operator-proxy", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ path: backendPath, body: body ?? {} }),
      cache: "no-store",
    });
    const text = await res.text();
    let data: T | null = null;
    try {
      data = text ? (JSON.parse(text) as T) : null;
    } catch {
      data = null;
    }
    return {
      ok: res.ok,
      status: res.status,
      url: `/operator-proxy → ${backendPath}`,
      data,
      error: res.ok ? null : text.slice(0, 300),
      contentType: "application/json",
      rawKeys: data && typeof data === "object" ? Object.keys(data as object) : [],
      authMode: "server_proxy",
    };
  }
  const session = sessionOperatorHeaders();
  if (!session["X-Operator-Token"]) {
    return {
      ok: false,
      status: 403,
      url: backendPath,
      data: null,
      error:
        "Operator authorization required. Configure OPERATOR_SECRET on frontend service or enter session token in Settings.",
      contentType: null,
      rawKeys: [],
      authMode: "none",
    };
  }
  const direct = await fetch(buildApiUrl(backendPath), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...session,
    },
    body: JSON.stringify(body ?? {}),
    cache: "no-store",
  });
  const text = await direct.text();
  let data: T | null = null;
  if (text) {
    try {
      data = JSON.parse(text) as T;
    } catch {
      data = null;
    }
  }
  return {
    ok: direct.ok,
    status: direct.status,
    url: backendPath,
    data,
    error: direct.ok ? null : text.slice(0, 300),
    contentType: direct.headers.get("content-type"),
    rawKeys: data && typeof data === "object" ? Object.keys(data as object) : [],
    authMode: "session_token",
  };
}
