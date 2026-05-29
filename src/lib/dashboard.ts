import type { DashboardData } from "@/types/dashboard";
import { apiGet } from "@/lib/apiClient";
import { fetchAlpacaConnected } from "@/lib/brokerStatus";

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
    },
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

export async function getDashboardData(): Promise<DashboardData> {
  const [cockpit, health, alpacaConnected] = await Promise.all([
    apiGet<Record<string, unknown>>("/api/mission-control/status", {
      forServer: true,
      timeoutMs: 3500,
    }),
    apiGet<Record<string, unknown>>("/api/health", {
      forServer: true,
      timeoutMs: 2500,
    }),
    fetchAlpacaConnected({ forServer: true, timeoutMs: 2500 }),
  ]);

  const fallback = emptyDashboard(
    cockpit.error || health.error || `API unavailable (${cockpit.status || health.status})`
  );
  const cockpitData = cockpit.data || {};
  const control = (cockpitData.control as Record<string, unknown> | undefined) || {};
  const account = (cockpitData.account as Record<string, unknown> | undefined) || {};
  const watchlist = (cockpitData.watchlist as Record<string, unknown> | undefined) || {};
  const crypto = (watchlist.crypto as Record<string, unknown> | undefined) || {};

  fallback.lastSyncAt = String(cockpitData.generated_at_utc || new Date().toISOString());
  fallback.lastSync = fallback.lastSyncAt;
  fallback.systemStatus.alpacaConnected = Boolean(
    alpacaConnected || cockpitData.alpaca_connected || account.connected || health.data?.alpaca_configured
  );
  fallback.systemStatus.databaseConnected = health.ok || cockpit.ok;
  fallback.systemStatus.geminiConfigured = Boolean(health.data?.gemini_configured);
  fallback.statusChips = [
    { label: "U.S. Stocks", value: "Session aware", variant: "neutral" },
    { label: "Crypto", value: "OPEN", variant: "success" },
    {
      label: "AI Mode",
      value: control.paper_learning_on ? "LEARNING" : "WATCHING",
      variant: control.paper_learning_on ? "info" : "neutral",
    },
    { label: "Risk Mode", value: "PAPER ONLY", variant: "info" },
  ];
  fallback.accountSurvival.status = fallback.systemStatus.alpacaConnected ? "waiting" : "not_connected";
  fallback.accountSurvival.capital = typeof account.equity === "number" ? account.equity : null;
  fallback.accountSurvival.message = fallback.systemStatus.alpacaConnected
    ? "Shell loaded from lightweight broker truth."
    : fallback.accountSurvival.message;
  fallback.marketRadarMeta.opportunitiesScanned =
    typeof crypto.usd_pairs === "number" ? crypto.usd_pairs : fallback.marketRadarMeta.opportunitiesScanned;
  fallback.marketRadarMeta.message = cockpit.ok
    ? "Open the cockpit for scanner and shortlist truth."
    : fallback.marketRadarMeta.message;
  return fallback;
}

export function getDiagnosticBundleUrl(): string {
  return "/reports";
}
