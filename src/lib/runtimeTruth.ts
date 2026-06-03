import { apiGet } from "@/lib/apiClient";

export type RuntimeTruth = {
  status?: string;
  generated_at?: string;
  live_locked?: boolean;
  broker_mode?: string;
  broker_connected?: boolean;
  paper_broker?: boolean;
  paper_orders_enabled?: boolean;
  paper_entry_ready?: boolean;
  scheduler_enabled?: boolean;
  last_tick_at?: string | null;
  next_tick_at?: string | null;
  shadow_league_enabled?: boolean;
  shadow_count?: number;
  reason_shadow_count_zero?: string | null;
  shadow_ui_state?: string;
  paper_candidate_count?: number;
  why_no_trade?: string | null;
  current_top_blocker?: { code?: string; label?: string } | null;
  positions_count?: number;
  active_orders_count?: number;
  kill_switch_clear?: boolean;
  stock_lane_mode?: string;
  data_degraded?: boolean;
  degraded_reason?: string | null;
  account_equity?: number | null;
  funnel_counts?: Record<string, number | null>;
};

export async function fetchRuntimeTruth(options?: { forServer?: boolean; timeoutMs?: number }) {
  return apiGet<RuntimeTruth>("/api/runtime/summary", {
    forServer: options?.forServer,
    timeoutMs: options?.timeoutMs ?? 5000,
  });
}

export function brokerLabel(truth: RuntimeTruth | null | undefined, degraded?: boolean): string {
  if (degraded && truth?.paper_broker) return "Status degraded";
  if (truth?.data_degraded && truth?.paper_broker) return "Degraded snapshot";
  if (truth?.broker_connected && truth?.paper_broker) return "Paper OK";
  if (truth?.paper_broker && truth?.paper_orders_enabled) return "Paper ready";
  if (truth?.paper_broker) return "Paper broker";
  return "Offline";
}

export function showNotConnectedWarning(truth: RuntimeTruth | null | undefined): boolean {
  if (!truth) return false;
  if (truth.data_degraded && truth.paper_broker) return false;
  if (truth.paper_broker && truth.paper_orders_enabled) return false;
  return !truth.broker_connected && !truth.paper_broker;
}
