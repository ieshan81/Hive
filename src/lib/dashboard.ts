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
      { label: "U.S. Stocks", value: "Calendar unavailable", variant: "neutral" },
      { label: "Crypto", value: "OPEN", variant: "success" },
      { label: "AI Mode", value: "OFFLINE", variant: "neutral" },
      { label: "Risk Mode", value: "FORMULA CAGE", variant: "info" },
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
  const [result, alpacaConnected] = await Promise.all([
    apiGet<DashboardData>("/api/dashboard", {
      forServer: true,
      timeoutMs: 28000,
    }),
    fetchAlpacaConnected({ forServer: true, timeoutMs: 6000 }),
  ]);
  if (!result.ok || !result.data) {
    const fallback = emptyDashboard(
      result.error || `API unavailable (${result.status}) — ${result.url}`
    );
    if (alpacaConnected) {
      fallback.systemStatus.alpacaConnected = true;
      if (fallback.accountSurvival.status === "not_connected") {
        fallback.accountSurvival.status = "waiting";
        fallback.accountSurvival.message = "Dashboard loading — Alpaca connected";
        fallback.accountSurvival.riskStatusMessage = "Account details loading";
      }
    }
    return fallback;
  }
  if (alpacaConnected && !result.data.systemStatus.alpacaConnected) {
    result.data.systemStatus.alpacaConnected = true;
  }
  return result.data;
}

export function getDiagnosticBundleUrl(): string {
  return "/reports";
}
