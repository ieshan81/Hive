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
  | "stale"
  | "skipped"
  | "empty"
  | "not_connected"
  | "waiting"
  | "not_configured"
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
  aiReviewFreshness?: string;
  whatILearned?: string[];
  whatIWillAvoid?: string[];
  whatIWillTestNext?: string[];
  stats: {
    decisionsToday: number;
    approved: number;
    blocked: number;
    deferred?: number;
    ordersSubmitted?: number;
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
  assetClass?: string;
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

export interface PortfolioDecisionRow {
  symbol: string;
  rank: number | null;
  score: number | null;
  status: string;
  reason: string | null;
  selected: boolean;
}

export interface ExecutionLogSummary {
  eventId?: string;
  symbol?: string;
  status?: string;
  rejectReason?: string | null;
  limitPrice?: number | null;
  tif?: string | null;
}

export interface OrderRow {
  symbol: string;
  side: string;
  qty: number;
  status: string;
  brokerOrderId?: string | null;
  clientOrderId?: string | null;
  filledAvgPrice?: number | null;
  orderType?: string;
}

export interface PositionRow {
  symbol: string;
  qty: number;
  avgEntryPrice?: number;
  currentPrice?: number;
  unrealizedPl?: number;
  unrealizedPlPct?: number;
}

export interface DashboardData {
  lastSync: string;
  lastSyncAt?: string | null;
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
    refreshedAt: string | null;
    opportunitiesScanned: number;
  };
  backtest: {
    status: DataStatus;
    message: string;
  };
  session?: Record<string, unknown>;
  promotionStage?: string;
  portfolioGate?: {
    cycleRunId?: string | null;
    rankedCount: number;
    selectedCount: number;
    deferredCount: number;
    topN: number;
    decisions: PortfolioDecisionRow[];
    truthMessage: string;
  };
  executionPolicy?: {
    paperOrdersEnabled: boolean;
    liveOrdersEnabled: boolean;
    brokerMode?: string;
    orderTypeDefault?: string;
    maxOrdersPerCycle?: number;
    latestLog?: ExecutionLogSummary | null;
    whyNoOrder?: string | null;
    selectedSymbol?: string | null;
    paper_execution_blockers?: string[];
    paper_execution_ready?: boolean;
  };
  latestCycle?: {
    cycleRunId?: string | null;
    riskBlocked: number;
    riskApproved: number;
    portfolioSelected: number;
    portfolioDeferred: number;
    ordersSubmitted: number;
    observations: number;
  };
  orders?: {
    cycleRunId?: string | null;
    count: number;
    items: OrderRow[];
  };
  positionsPanel?: {
    count: number;
    items: PositionRow[];
  };
  riskCageExtras?: Record<string, unknown>;
}
