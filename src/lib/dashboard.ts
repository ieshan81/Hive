import type { DashboardData } from "@/types/dashboard";
import { apiGet, buildApiUrl } from "@/lib/apiClient";

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
      { label: "Market Status", value: "UNKNOWN", variant: "neutral" },
      { label: "AI Mode", value: "OFFLINE", variant: "neutral" },
      { label: "Risk Mode", value: "SURVIVAL", variant: "info" },
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
      refreshedAt: "—",
      opportunitiesScanned: 0,
    },
    backtest: { status: "not_run", message: "Backtest not run yet" },
  };
}

export async function getDashboardData(): Promise<DashboardData> {
  const result = await apiGet<DashboardData>("/api/dashboard", { forServer: true });
  if (!result.ok || !result.data) {
    return emptyDashboard(
      result.error || `API unavailable (${result.status}) — ${result.url}`
    );
  }
  return result.data;
}

export function getDiagnosticBundleUrl(): string {
  return buildApiUrl("/api/diagnostic-bundle/download", true);
}
