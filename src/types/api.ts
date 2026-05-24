/** API response contracts (normalized after fetch). */

export interface MemoryGraphNode {
  id: string;
  label: string;
  type: string;
  category?: string;
  severity?: string;
  confidence?: number;
  status?: string;
  badge?: string;
  count?: number;
  color?: string;
  x: number;
  y: number;
  symbol?: string;
  strategy_name?: string;
  memory_type?: string;
}

export interface MemoryGraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  weight?: number;
  evidence_count?: number;
}

export interface MemoryGraphResponse {
  status?: string;
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

export interface LessonNodeSummary {
  node_id?: string;
  lesson_id?: number;
  id?: number;
  title: string;
  category?: string;
  memory_type?: string;
  severity?: string;
  summary?: string;
  [key: string]: unknown;
}

export interface Position {
  symbol: string;
  qty: number;
  avg_entry_price?: number;
  avgEntryPrice?: number;
  current_price?: number;
  market_value?: number;
  unrealized_pl?: number;
  unrealized_pl_pct?: number;
  side?: string;
  source?: string;
  [key: string]: unknown;
}

export interface PositionState {
  symbol: string;
  signal_id?: number;
  order_id?: string;
  cycle_run_id?: string;
  strategy?: string;
  fee_adjusted_qty?: number;
  fee_qty?: number;
  fee_pct?: number;
  broker_qty?: number;
  [key: string]: unknown;
}

export interface OrderRecord {
  symbol: string;
  side: string;
  status: string;
  broker_order_id?: string;
  client_order_id?: string;
  alpaca_order_id?: string;
  qty?: number;
  requested_qty?: number;
  filled_qty?: number;
  limit_price?: number;
  filled_avg_price?: number;
  order_type?: string;
  type?: string;
  tif?: string;
  [key: string]: unknown;
}

export interface TradeHistoryRecord {
  trade_id?: number;
  symbol: string;
  side: string;
  outcome?: string;
  status?: string;
  entry_price?: number;
  exit_price?: number;
  qty?: number;
  quantity?: number;
  realized_pl?: number;
  [key: string]: unknown;
}

export interface ApprovedDecision {
  symbol: string;
  side?: string;
  strategy?: string;
  risk_status?: string;
  portfolio_status?: string;
  broker_order_id?: string;
  [key: string]: unknown;
}

export interface BlockedDecision {
  symbol: string;
  strategy?: string;
  block_reason_code?: string;
  human_reason?: string;
  [key: string]: unknown;
}

export interface DeferredDecision {
  symbol: string;
  reason_code?: string;
  ranking_score?: number;
  [key: string]: unknown;
}

export interface DecisionLatestResponse {
  status?: string;
  cycle_run_id?: string | null;
  approved?: ApprovedDecision[];
  blocked?: BlockedDecision[];
  deferred?: DeferredDecision[];
  orders_submitted?: unknown[];
  lessons_created?: unknown[];
  counts?: Record<string, number>;
}

export type DataSource = "live_api" | "dashboard_snapshot" | "empty";

export interface PanelLoadMeta {
  source: DataSource;
  lastUpdated: string;
  endpoint?: string;
  error?: string;
  httpStatus?: number;
}
