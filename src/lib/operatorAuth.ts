/** Operator authorization — never use NEXT_PUBLIC for backend secrets. */

const SESSION_KEY = "hive_operator_session_token";

export const MUTATING_API_PATHS = [
  "/api/fast-training/enable",
  "/api/fast-training/disable",
  "/api/fast-training/run-once",
  "/api/fast-training/monitor-exits",
  "/api/fast-training/exit-only/enable",
  "/api/fast-training/exit-only/disable",
  "/api/fast-training/exit-only/run",
  "/api/cycle/run",
  "/api/settings/clear-ghost-rows",
  "/api/strategies/import",
] as const;

export function isMutatingPath(path: string): boolean {
  return MUTATING_API_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

export function getSessionOperatorToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem(SESSION_KEY)?.trim() || null;
  } catch {
    return null;
  }
}

export function setSessionOperatorToken(token: string): void {
  sessionStorage.setItem(SESSION_KEY, token.trim());
}

export function clearSessionOperatorToken(): void {
  sessionStorage.removeItem(SESSION_KEY);
}

export function hasSessionOperatorToken(): boolean {
  return Boolean(getSessionOperatorToken());
}
