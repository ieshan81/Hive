/**
 * Strict allowlist for POST paths forwarded by /operator-proxy.
 * Never use wildcards — exact paths or known prefixes only.
 *
 * Risk classes (Phase 11 narrowing):
 *  - destructive: NEVER proxied (denied). Rebuild + danger-zone must be called directly with the
 *    operator token + their server-side confirmation phrase, never through the broad proxy.
 *  - admin: exact paths only.
 *  - paper_control / read_only: paper-only operator controls (server enforces paper + live-lock).
 */

/** Destructive paths that must NEVER be forwarded by the proxy (denied even if matched elsewhere). */
export const DENIED_EXACT_PATHS = ["/api/rebuild"] as const;
export const DENIED_PREFIXES = ["/api/danger-zone/", "/api/rebuild"] as const;

/** Admin paths — exact only (no prefix fan-out). */
export const ALLOWED_POST_EXACT_PATHS = [
  "/api/admin/repair-database-bootstrap",
  "/api/diagnostics/export/run",
  "/api/cycle/run",
  "/api/settings/clear-ghost-rows",
  "/api/settings/clear-ui-cache",
  "/api/settings/export-brain-bundle",
  "/api/settings/resync-broker-truth",
] as const;

export const ALLOWED_POST_PREFIXES = [
  "/api/market-data/",
  "/api/universe/",
  "/api/execution/paper/",
  "/api/backtesting/",
  "/api/lab/",
  "/api/research/",
  "/api/alpha-factory/",
  "/api/research/targeted-experiment/",
  "/api/tradingview/",
  "/api/live-flags/",
  "/api/ai-advisor/",
  "/api/hive-brain/",
  "/api/memory/",
  "/api/news/",
  "/api/scanners/",
  "/api/paper/",
  "/api/weights/",
  "/api/fast-training/",
  "/api/autonomous-paper-learning/",
  "/api/paper-learning/",
  "/api/positions/",
  "/api/strategy-proposals/",
  "/api/live-promotion/",
  "/api/strategies/",
  // Paper-trading settings operator panel. Live trading flags cannot be touched — server enforces.
  "/api/settings/paper-trading/",
] as const;

/** Risk classification for review/verifiers. Destructive prefixes are DENIED, not allowed. */
export const PROXY_RISK_CLASSES: Record<string, { class: "destructive" | "admin" | "paper_control"; reason: string }> = {
  "/api/rebuild": { class: "destructive", reason: "hard nuke + fresh cycles — denied via proxy; call directly with phrase" },
  "/api/danger-zone/": { class: "destructive", reason: "nuke/reset — denied via proxy; phrase-protected direct call only" },
  "/api/admin/repair-database-bootstrap": { class: "admin", reason: "schema repair; exact path only" },
  "/api/diagnostics/export/run": { class: "admin", reason: "diagnostic export; exact path only" },
  "/api/execution/paper/": { class: "paper_control", reason: "paper execution controls; server enforces paper + live-lock" },
  "/api/paper-learning/": { class: "paper_control", reason: "paper learning controls; server enforces paper + live-lock" },
  "/api/autonomous-paper-learning/": { class: "paper_control", reason: "paper scheduler controls; server enforces paper + live-lock" },
  "/api/universe/": { class: "paper_control", reason: "universe scan/refresh; read/compute" },
  "/api/memory/": { class: "paper_control", reason: "memory governance; cannot trade" },
};

function isDenied(path: string): boolean {
  if ((DENIED_EXACT_PATHS as readonly string[]).includes(path)) return true;
  return DENIED_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix));
}

/** Only POST is proxied; callers must not forward GET/DELETE. */
export function isOperatorProxyPathAllowed(path: string): boolean {
  const p = path.trim();
  if (!p.startsWith("/api/")) return false;
  if (p === "/api/" || p === "/api/*") return false; // never a wildcard
  if (isDenied(p)) return false; // destructive routes are never proxied
  if ((ALLOWED_POST_EXACT_PATHS as readonly string[]).includes(p)) return true;
  return ALLOWED_POST_PREFIXES.some((prefix) => p === prefix || p.startsWith(prefix));
}
