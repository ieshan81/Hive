/**
 * Central API client — single source for backend URL and fetch behavior.
 * Next.js: use NEXT_PUBLIC_API_URL (also reads VITE_API_BASE_URL for compatibility).
 */

export type ApiFetchResult<T> = {
  ok: boolean;
  status: number;
  url: string;
  data: T | null;
  error: string | null;
  contentType: string | null;
  rawKeys: string[];
  corsBlocked?: boolean;
};

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

function operatorHeaders(): Record<string, string> {
  const token =
    typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_OPERATOR_TOKEN || ""
      : "";
  if (!token.trim()) return {};
  return { "X-Operator-Token": token.trim() };
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
  options?: { forServer?: boolean; signal?: AbortSignal }
): Promise<ApiFetchResult<T>> {
  const url = buildApiUrl(path, options?.forServer);
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: options?.signal,
    });
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
    const msg = e instanceof Error ? e.message : String(e);
    const corsBlocked =
      typeof window !== "undefined" &&
      (msg.includes("Failed to fetch") || msg.includes("NetworkError"));
    return {
      ok: false,
      status: 0,
      url,
      data: null,
      error: corsBlocked
        ? `CORS or network blocked: ${msg} (called ${url})`
        : msg,
      contentType: null,
      rawKeys: [],
      corsBlocked,
    };
  }
}

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
        ...operatorHeaders(),
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
