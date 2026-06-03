import type { DashboardData } from "@/types/dashboard";
import { apiGet } from "@/lib/apiClient";
import type { RuntimeTruth } from "@/lib/runtimeTruth";
import { fetchRuntimeTruth } from "@/lib/runtimeTruth";

function emptyDashboard(message: string): DashboardData {
  return {
    lastSync: "Not synced",
    systemStatus: {
      alpacaConnected: false,
      geminiConfigured: false,
      databaseConnected: false,
      killSwitchActive: false,
      paperTradingOnly: true,
      liveTradingEnabled: false,
      paperBroker: false,
      runtimeDegraded: false,
    },
    runtimeTruth: null,
    statusChips: [
      { label: "U.S. Stocks", value: "Session aware", variant: "neutral" },
      { label: "Crypto", value: "OPEN", variant: "success" },
      { label: "AI Mode", value: "WATCHING", variant: "neutral" },
      { label: "Risk Mode", value: "PAPER ONLY", variant: "info" },
    ],
    accountSurvival: {
      status: "not_connected",
      message,
      capital: null,
      plToday: null,
      plTodayPct: null,
      drawdown: null,
      riskStatus: "UNKNOWN",
      riskStatusMessage: message,
      riskLevel: 0,
      dailyLossUsed: 0,
      dailyLossLimit: 0,
      weeklyLossUsed: 0,
      weeklyLossLimit: 0,
      sparklines: { capital: [], pl: [], drawdown: [] },
    },
    aiFundManager: {
      status: "not_configured",
      message,
      decision: null,
      decisionMessage: "API unavailable",
      confidence: null,
      confidenceLabel: "N/A",
      reasonSummary: message,
      memoryUsedPct: null,
      approvalStatus: "PENDING",
      approvalMessage: message,
      stats: { decisionsToday: 0, approved: 0, blocked: 0, learnedLessons: 0 },
    },
    memoryGraph: { status: "empty", message: "Memory empty", nodes: [] },
    strategies: [],
    riskRules: [],
    marketAssets: [],
    monteCarlo: {
      status: "unavailable",
      message: "Monte Carlo unavailable",
      goalFrom: null,
      goalTo: 500,
      probabilityPct: null,
      horizonDays: 240,
      maxDrawdownPct: null,
      drawdownConfidence: 95,
      simulations: [],
      medianPath: [],
      scenarios: [],
    },
    marketRadarMeta: {
      status: "empty",
      message,
      refreshedAt: "-",
      opportunitiesScanned: 0,
    },
    backtest: { status: "not_run", message: "Backtest not run yet" },
  };
}

function applyRuntimeTruth(fallback: DashboardData, truth: RuntimeTruth | null, healthOk: boolean) {
  if (!truth) return;
  fallback.runtimeTruth = truth;
  fallback.lastSyncAt = truth.generated_at || fallback.lastSyncAt;
  fallback.lastSync = fallback.lastSyncAt || fallback.lastSync;
  fallback.systemStatus.alpacaConnected = Boolean(truth.broker_connected);
  fallback.systemStatus.paperBroker = Boolean(truth.paper_broker);
  fallback.systemStatus.runtimeDegraded = Boolean(truth.data_degraded);
  fallback.systemStatus.killSwitchActive = truth.kill_switch_clear === false;
  fallback.systemStatus.databaseConnected = healthOk;
  fallback.accountSurvival.status = truth.broker_connected ? "waiting" : "not_connected";
  fallback.accountSurvival.capital = typeof truth.account_equity === "number" ? truth.account_equity : null;
  fallback.accountSurvival.message = truth.data_degraded
    ? "Status degraded — using latest runtime snapshot."
    : truth.broker_connected
      ? "Paper broker connected — live locked."
      : truth.paper_broker
        ? "Paper broker configured — awaiting sync."
        : fallback.accountSurvival.message;
  fallback.statusChips = [
    { label: "U.S. Stocks", value: "Session aware", variant: "neutral" },
    { label: "Crypto", value: "OPEN", variant: "success" },
    {
      label: "Scheduler",
      value: truth.scheduler_enabled ? "ON" : "OFF",
      variant: truth.scheduler_enabled ? "success" : "neutral",
    },
    { label: "Risk Mode", value: truth.live_locked ? "PAPER ONLY" : "CHECK", variant: "info" },
  ];
}

export async function getDashboardData(): Promise<DashboardData> {
  const [runtime, health] = await Promise.all([
    fetchRuntimeTruth({ forServer: true, timeoutMs: 5000 }),
    apiGet<Record<string, unknown>>("/api/health", { forServer: true, timeoutMs: 2500 }),
  ]);

  const fallback = emptyDashboard(
    runtime.error || health.error || `API unavailable (${runtime.status || health.status})`
  );
  if (runtime.ok && runtime.data) {
    applyRuntimeTruth(fallback, runtime.data, health.ok);
  }
  fallback.systemStatus.geminiConfigured = Boolean(health.data?.gemini_configured);
  return fallback;
}

export function getDiagnosticBundleUrl(): string {
  return "/reports";
}
