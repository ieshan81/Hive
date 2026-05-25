/** Beginner-readable labels — no raw enums on main UI. */

export const LABELS = {
  entries_allowed: "Can the bot open a new paper trade?",
  entries_eligible: "Signals found",
  can_submit_orders: "Final permission to place paper order",
  preflight: "Safety check before order",
  live_trading_locked: "Live trading is locked",
  paper_order_rejected: "Paper order rejected",
  marketable_limit_ioc: "Instant market-price limit order",
  BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY:
    "Broker is flat; an old buy exists in history only (not an open position).",
  ghost_position: "Local record mismatch",
  training_mode_disabled: "Training Mode is OFF",
  fast_training_loop_disabled: "Fast training loop is off (Railway uses run-once only)",
} as const;

export function friendlyClassification(code: string | undefined | null): string {
  if (!code) return "Unknown";
  if (code === "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY") {
    return LABELS.BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY;
  }
  return code.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export function friendlyBlocker(code: string): string {
  const map: Record<string, string> = {
    training_mode_disabled: "Training Mode is OFF — the bot cannot open new paper trades.",
    fast_training_loop_disabled: "Fast training is off. Use Run Once when training is enabled.",
    fast_training_execute_orders_disabled: "Order execution is disabled in settings.",
    open_position_exists: "Historical record only — broker holds no open position.",
    open_position_blocks_duplicate_entry: "An open broker position blocks a duplicate entry.",
  };
  if (map[code]) return map[code];
  if (code.startsWith("reconciliation:")) return `Reconciliation: ${code.split(":").slice(1).join(" ")}`;
  return code.replace(/_/g, " ");
}

export function formatPrice(n: number | null | undefined, decimals = 6): string {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(decimals);
}

export function formatQty(n: number | null | undefined, decimals = 4): string {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(decimals);
}
