export type NavItemId =
  | "overview"
  | "ai-manager"
  | "strategies"
  | "market-radar"
  | "risk-cage"
  | "backtesting"
  | "performance"
  | "reports"
  | "settings";

export type DataStatus =
  | "ok"
  | "active"
  | "empty"
  | "not_connected"
  | "waiting"
  | "not_configured"
  | "waiting"
  | "unavailable"
  | "not_configured"
  | "not_run"
  | "error";

export interface StatusChip {
  label: string;
  value: string;
  variant: "success" | "info" | "neutral" | "warning";
}

export interface AccountSurvivalData {
  status: DataStatus;
  message: string | null;
  capital: number | null;
  plToday: number | null;
  plTodayPct: number | null;
  drawdown: number | null;
  riskStatus: string;
  riskStatusMessage: string;
  riskLevel: number;
  dailyLossUsed: number;
  dailyLossLimit: number;
  weeklyLossUsed: number;
  weeklyLossLimit: number;
  sparklines: {
    capital: number[];
    pl: number[];
    drawdown: number[];
  };
}

export interface AIFundManagerData {
  status: DataStatus;
  message: string | null;
  decision: string | null;
  decisionMessage: string;
  confidence: number | null;
  confidenceLabel: string;
  reasonSummary: string;
  memoryUsedPct: number | null;
  approvalStatus: string;
  approvalMessage: string;
  stats: {
    decisionsToday: number;
    approved: number;
    blocked: number;
    learnedLessons: number;
  };
}

export interface MemoryNode {
  id: string;
  label: string;
  count: number;
  color: string;
  x: number;
  y: number;
}

export interface MemoryGraphData {
  status: DataStatus;
  message: string | null;
  nodes: MemoryNode[];
}

export interface StrategyData {
  id: string;
  name: string;
  status: string;
  performance7d: number | null;
  confidence: number;
  exposure: number;
  sparkline: number[];
  message?: string | null;
}

export interface RiskRule {
  id: string;
  text: string;
  enforced: boolean;
}

export interface MarketAsset {
  symbol: string;
  name: string;
  liquidity: number | null;
  sentiment: number | null;
  volatility: number | null;
  spread: string;
  eligibility: string;
  message?: string | null;
}

export interface MonteCarloScenario {
  percentile: string;
  value: number;
}

export interface MonteCarloData {
  status: DataStatus;
  message: string | null;
  goalFrom: number | null;
  goalTo: number;
  probabilityPct: number | null;
  horizonDays: number;
  maxDrawdownPct: number | null;
  drawdownConfidence: number;
  simulations: number[][];
  medianPath: number[];
  scenarios: MonteCarloScenario[];
}

export interface SystemStatus {
  alpacaConnected: boolean;
  geminiConfigured: boolean;
  databaseConnected: boolean;
  killSwitchActive: boolean;
  paperTradingOnly: boolean;
  liveTradingEnabled: boolean;
}

export interface DashboardData {
  lastSync: string;
  systemStatus: SystemStatus;
  statusChips: StatusChip[];
  accountSurvival: AccountSurvivalData;
  aiFundManager: AIFundManagerData;
  memoryGraph: MemoryGraphData;
  strategies: StrategyData[];
  riskRules: RiskRule[];
  marketAssets: MarketAsset[];
  monteCarlo: MonteCarloData;
  marketRadarMeta: {
    status: DataStatus;
    message: string | null;
    refreshedAt: string;
    opportunitiesScanned: number;
  };
  backtest: {
    status: DataStatus;
    message: string;
  };
}
