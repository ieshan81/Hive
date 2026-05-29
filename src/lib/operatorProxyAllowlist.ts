/**
 * Strict allowlist for POST paths forwarded by /operator-proxy.
 * Never use wildcards — exact paths or known prefixes only.
 */

export const ALLOWED_POST_EXACT_PATHS = [
  "/api/danger-zone/nuke-everything",
  "/api/danger-zone/ready-for-live-cleanup",
  "/api/admin/repair-database-bootstrap",
  "/api/diagnostics/export/run",
] as const;

export const ALLOWED_POST_PREFIXES = [
  "/api/market-data/",
  "/api/universe/",
  "/api/execution/paper/",
  "/api/backtesting/",
  "/api/lab/",
  "/api/research/",
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
  "/api/cycle/run",
  "/api/settings/clear-ghost-rows",
  "/api/settings/clear-ui-cache",
  "/api/settings/export-brain-bundle",
  "/api/strategies/",
  "/api/settings/resync-broker-truth",
  // Paper-trading settings operator panel (Phase 5/6).
  // Live trading flags cannot be touched by these endpoints — server enforces.
  "/api/settings/paper-trading/",
] as const;

/** Only POST is proxied; callers must not forward GET/DELETE. */
export function isOperatorProxyPathAllowed(path: string): boolean {
  const p = path.trim();
  if (!p.startsWith("/api/")) return false;
  if ((ALLOWED_POST_EXACT_PATHS as readonly string[]).includes(p)) return true;
  return ALLOWED_POST_PREFIXES.some((prefix) => p === prefix || p.startsWith(prefix));
}
