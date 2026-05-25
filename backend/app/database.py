from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session
from sqlalchemy import Column, JSON, Text

from app.config import settings


class AccountSnapshot(SQLModel, table=True):
    __tablename__ = "account_snapshots"
    id: Optional[int] = Field(default=None, primary_key=True)
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    portfolio_value: float = 0.0
    daily_pl: float = 0.0
    daily_pl_pct: float = 0.0
    drawdown_pct: float = 0.0
    equity_peak: float = 0.0
    raw_payload: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class PositionSnapshot(SQLModel, table=True):
    __tablename__ = "position_snapshots"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    qty: float = 0.0
    side: str = "long"
    avg_entry_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pl: float = 0.0
    unrealized_pl_pct: float = 0.0
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class OrderRecord(SQLModel, table=True):
    __tablename__ = "orders"
    id: Optional[int] = Field(default=None, primary_key=True)
    alpaca_order_id: Optional[str] = Field(default=None, index=True)
    broker_client_order_id: Optional[str] = Field(default=None, index=True)
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    signal_id: Optional[int] = Field(default=None, index=True)
    symbol: str = Field(index=True)
    side: str
    qty: float
    order_type: str = "market"
    status: str = "pending"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None
    filled_avg_price: Optional[float] = None
    raw_payload: Optional[dict] = Field(default=None, sa_column=Column(JSON))


class TradeRecord(SQLModel, table=True):
    __tablename__ = "trades"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    strategy: Optional[str] = Field(default=None, index=True)
    side: str
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float
    return_pct: Optional[float] = None
    pl_dollars: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    status: str = "open"


class ActivityLog(SQLModel, table=True):
    __tablename__ = "activity_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    message: str
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BlockedTrade(SQLModel, table=True):
    __tablename__ = "blocked_trades"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    strategy: Optional[str] = None
    side: str
    reason: str
    block_reason_code: Optional[str] = Field(default=None, index=True)
    human_reason: Optional[str] = None
    risk_rule: Optional[str] = None
    evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    risk_engine_result: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    risk_checks_failed: Optional[list] = Field(default=None, sa_column=Column(JSON))
    proposed_qty: Optional[float] = None
    signal_id: Optional[int] = Field(default=None, index=True)
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RiskEvent(SQLModel, table=True):
    __tablename__ = "risk_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str
    severity: str = "info"
    message: str
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategySignal(SQLModel, table=True):
    __tablename__ = "strategy_signals"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str = Field(index=True)
    symbol: str = Field(index=True)
    asset_class: str = Field(default="stock", index=True)
    signal: str
    side: str = "hold"
    strength: float = 0.0
    confidence: float = 0.0
    status: str = Field(default="generated", index=True)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    signal_metadata: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    signal_type: str = Field(default="entry", index=True)  # entry, exit, observation
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyState(SQLModel, table=True):
    __tablename__ = "strategy_states"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str = Field(index=True, unique=True)
    status: str = "inactive"
    status_reason: Optional[str] = None
    performance_7d: Optional[float] = None
    confidence: float = 0.0
    exposure_pct: float = 0.0
    cooling_until: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SymbolCandidate(SQLModel, table=True):
    __tablename__ = "symbol_candidates"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    name: Optional[str] = None
    asset_class: str = Field(default="stock", index=True)
    liquidity_score: Optional[float] = None
    sentiment_score: Optional[float] = None
    volatility_score: Optional[float] = None
    spread_pct: Optional[float] = None
    spread_display: Optional[str] = None
    eligibility: str = "unknown"
    source: str = "alpaca"
    scanned_at: datetime = Field(default_factory=datetime.utcnow)


class AIReview(SQLModel, table=True):
    __tablename__ = "ai_reviews"
    id: Optional[int] = Field(default=None, primary_key=True)
    subject_type: str
    subject_id: Optional[str] = None
    decision: str
    review_status: str = Field(default="success", index=True)
    confidence: float = 0.0
    summary: str
    payload: dict = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIMemory(SQLModel, table=True):
    __tablename__ = "ai_memories"
    id: Optional[int] = Field(default=None, primary_key=True)
    memory_type: str
    symbol: Optional[str] = Field(default=None, index=True)
    strategy: Optional[str] = None
    event: str
    lesson: str
    confidence: float = 0.5
    strength: float = 0.5
    decay_rate: float = 0.05
    outcome: Optional[str] = None
    linked_trade_id: Optional[int] = None
    action_taken: Optional[str] = None
    result_after_action: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_confirmed_at: Optional[datetime] = None


class AIUsageLog(SQLModel, table=True):
    __tablename__ = "ai_usage_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    model: str = "gemini-3.5-flash"
    purpose: str
    mode: str = "quick"
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    status: str = "ok"
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIConfigProposal(SQLModel, table=True):
    __tablename__ = "ai_config_proposals"
    id: Optional[int] = Field(default=None, primary_key=True)
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    proposed_by: str = "ai"
    config_patch: dict = Field(sa_column=Column(JSON))
    reason: str
    status: str = "proposed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIStrategyNote(SQLModel, table=True):
    __tablename__ = "ai_strategy_notes"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str = Field(index=True)
    cycle_run_id: Optional[str] = None
    note: str
    source: str = "ai"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SymbolMemory(SQLModel, table=True):
    __tablename__ = "symbol_memories"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    memory_key: str
    lesson: str
    strength: float = 0.5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyMemory(SQLModel, table=True):
    __tablename__ = "strategy_memories"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str = Field(index=True)
    memory_key: str
    lesson: str
    strength: float = 0.5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConfigCurrent(SQLModel, table=True):
    __tablename__ = "config_current"
    id: Optional[int] = Field(default=1, primary_key=True)
    config_json: dict = Field(sa_column=Column(JSON))
    version: int = 1
    activated_at: datetime = Field(default_factory=datetime.utcnow)


class ConfigHistory(SQLModel, table=True):
    __tablename__ = "config_history"
    id: Optional[int] = Field(default=None, primary_key=True)
    config_json: dict = Field(sa_column=Column(JSON))
    status: str = "proposed"
    reason: Optional[str] = None
    changed_by: str = "system"
    diff: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    activated_at: Optional[datetime] = None


class BacktestResult(SQLModel, table=True):
    __tablename__ = "backtest_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str
    symbols: list = Field(sa_column=Column(JSON))
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    num_trades: int = 0
    total_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    win_rate: Optional[float] = None
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    slippage_assumption: float = 0.0
    spread_assumption: float = 0.0
    fee_assumption: float = 0.0
    warnings: Optional[list] = Field(default=None, sa_column=Column(JSON))
    status: str = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MonteCarloResult(SQLModel, table=True):
    __tablename__ = "monte_carlo_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    starting_capital: float
    target_capital: float
    simulation_count: int = 0
    median_path: Optional[list] = Field(default=None, sa_column=Column(JSON))
    best_case: Optional[float] = None
    worst_case: Optional[float] = None
    probability_target: Optional[float] = None
    probability_drawdown: Optional[float] = None
    risk_of_ruin: Optional[float] = None
    assumptions: Optional[str] = Field(default=None, sa_column=Column(Text))
    warning: Optional[str] = None
    status: str = "unavailable"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SystemHealth(SQLModel, table=True):
    __tablename__ = "system_health"
    id: Optional[int] = Field(default=1, primary_key=True)
    alpaca_connected: bool = False
    database_connected: bool = False
    gemini_configured: bool = False
    kill_switch_active: bool = False
    last_account_sync: Optional[datetime] = None
    last_error: Optional[str] = None
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BrokerError(SQLModel, table=True):
    __tablename__ = "broker_errors"
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = "alpaca"
    operation: str
    message: str
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PortfolioDecision(SQLModel, table=True):
    __tablename__ = "portfolio_decisions"
    id: Optional[int] = Field(default=None, primary_key=True)
    cycle_run_id: str = Field(index=True)
    signal_id: int = Field(index=True)
    symbol: str = Field(index=True)
    side: str
    signal_type: str = "entry"
    portfolio_status: str = Field(index=True)
    portfolio_reason_code: Optional[str] = None
    human_reason: Optional[str] = None
    ranking_score: Optional[float] = None
    portfolio_rank: Optional[int] = None
    selected_for_execution: bool = False
    evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionLog(SQLModel, table=True):
    __tablename__ = "execution_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: str = Field(index=True)
    cycle_run_id: str = Field(index=True)
    signal_id: Optional[int] = Field(default=None, index=True)
    portfolio_decision_id: Optional[int] = None
    symbol: str = Field(index=True)
    side: str
    signal_type: str = "entry"
    requested_qty: Optional[float] = None
    requested_notional: Optional[float] = None
    limit_price: Optional[float] = None
    tif: Optional[str] = None
    bid_at_decision: Optional[float] = None
    ask_at_decision: Optional[float] = None
    mid_at_decision: Optional[float] = None
    reference_price: Optional[float] = None
    spread_pct_at_decision: Optional[float] = None
    atr14_at_decision: Optional[float] = None
    expected_move_pct: Optional[float] = None
    edge_over_cost: Optional[float] = None
    risk_pct: Optional[float] = None
    gates_passed_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    gates_failed_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    ai_review_id: Optional[int] = None
    broker_order_id: Optional[str] = Field(default=None, index=True)
    broker_client_order_id: Optional[str] = None
    submitted_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    filled_qty: Optional[float] = None
    filled_avg_price: Optional[float] = None
    commission: Optional[float] = None
    status: str = Field(default="pending", index=True)
    reject_reason: Optional[str] = None
    parent_signal_payload_hash: Optional[str] = None
    code_version_sha: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SymbolCooldown(SQLModel, table=True):
    __tablename__ = "symbol_cooldowns"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    reason: str = Field(index=True)
    active: bool = True
    expires_at: datetime
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyCooldown(SQLModel, table=True):
    __tablename__ = "strategy_cooldowns"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str = Field(index=True)
    reason: str
    active: bool = True
    expires_at: datetime
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AccountCooldown(SQLModel, table=True):
    __tablename__ = "account_cooldowns"
    id: Optional[int] = Field(default=None, primary_key=True)
    reason: str = Field(index=True)
    active: bool = True
    expires_at: datetime
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class KillSwitchEvent(SQLModel, table=True):
    __tablename__ = "kill_switch_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    switch_name: str = Field(index=True)
    active: bool = True
    severity: str = "critical"
    message: str
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deactivated_at: Optional[datetime] = None


class PromotionStatus(SQLModel, table=True):
    __tablename__ = "promotion_status"
    id: Optional[int] = Field(default=1, primary_key=True)
    current_stage: str = "PAPER"
    paper_started_at: Optional[datetime] = None
    metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    last_human_review_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LessonNode(SQLModel, table=True):
    """Evidence-based lesson memory — canonical store for Hive learning."""

    __tablename__ = "lesson_nodes"
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(default="trading_memory", index=True)
    memory_type: str = Field(index=True)
    title: str
    summary: str
    detailed_lesson: str
    severity: str = Field(default="MEDIUM", index=True)  # LOW|MEDIUM|HIGH|CRITICAL
    confidence: float = 0.85
    source: str = Field(default="deterministic", index=True)
    cycle_run_id: Optional[str] = Field(default=None, index=True)
    signal_id: Optional[int] = Field(default=None, index=True)
    order_id: Optional[int] = Field(default=None, index=True)
    broker_order_id: Optional[str] = Field(default=None, index=True)
    symbol: Optional[str] = Field(default=None, index=True)
    strategy_name: Optional[str] = Field(default=None, index=True)
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[str] = None
    evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    proposed_action: Optional[str] = None
    action_status: str = Field(default="none", index=True)
    status: str = Field(default="active", index=True)  # active|archived|deleted|resolved|ignored
    visible_in_graph: bool = Field(default=True)
    visible_to_ai: bool = Field(default=True)
    can_influence_ranking: bool = Field(default=True)
    human_review_status: str = Field(default="pending", index=True)
    archive_reason: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    pattern_key: Optional[str] = Field(default=None, index=True)
    occurrence_count: int = 1
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    tags: Optional[list] = Field(default=None, sa_column=Column(JSON))
    unsupported_claim: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryEdge(SQLModel, table=True):
    __tablename__ = "memory_edges"
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: str = Field(index=True)
    target_id: str = Field(index=True)
    relation: str = Field(index=True)
    weight: float = 1.0
    evidence_count: int = 1
    lesson_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryEvidence(SQLModel, table=True):
    __tablename__ = "memory_evidence"
    id: Optional[int] = Field(default=None, primary_key=True)
    lesson_id: int = Field(index=True)
    evidence_type: str
    payload: dict = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HistoricalBar(SQLModel, table=True):
    __tablename__ = "historical_bars"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    asset_class: str = Field(default="crypto", index=True)
    timeframe: str = Field(default="1Hour", index=True)
    timestamp: datetime = Field(index=True)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    source: str = Field(default="alpaca", index=True)
    adjusted: bool = False
    synthetic: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HistoricalDataCoverage(SQLModel, table=True):
    __tablename__ = "historical_data_coverage"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    timeframe: str = Field(index=True)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    requested_start_date: Optional[str] = None
    requested_end_date: Optional[str] = None
    actual_start_date: Optional[str] = None
    actual_end_date: Optional[str] = None
    data_is_recent: bool = True
    data_staleness_days: Optional[int] = None
    date_warning: Optional[str] = None
    rows_count: int = 0
    source: str = "alpaca"
    gaps_detected: bool = False
    gap_notes: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class HistoricalDataRequest(SQLModel, table=True):
    __tablename__ = "historical_data_requests"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    timeframe: str
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    status: str = Field(default="pending", index=True)
    rows_fetched: int = 0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HistoricalDataError(SQLModel, table=True):
    __tablename__ = "historical_data_errors"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    timeframe: str
    operation: str
    message: str
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyDefinition(SQLModel, table=True):
    __tablename__ = "strategy_definitions"
    strategy_id: str = Field(primary_key=True)
    strategy_name: str
    strategy_family: str = Field(index=True)
    parameters_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    asset_class: str = "crypto"
    universe: list = Field(default_factory=list, sa_column=Column(JSON))
    timeframe: str = "1Hour"
    status: str = Field(default="research_only", index=True)
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ResearchBacktestRun(SQLModel, table=True):
    __tablename__ = "research_backtest_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True)
    strategy_id: str = Field(index=True)
    parameter_set_id: Optional[str] = Field(default=None, index=True)
    symbols: list = Field(default_factory=list, sa_column=Column(JSON))
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    status: str = Field(default="pending", index=True)
    num_trades: int = 0
    metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    cost_model_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    sample_size: int = 0
    confidence_label: str = "low"
    warnings: Optional[list] = Field(default=None, sa_column=Column(JSON))
    estimated_spread: bool = True
    source: str = "research_lab"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ParameterSetResult(SQLModel, table=True):
    __tablename__ = "parameter_set_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    parameter_set_id: str = Field(index=True)
    run_id: str = Field(index=True)
    strategy_id: str = Field(index=True)
    parameters_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    num_trades: int = 0
    win_rate: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    exposure_pct: Optional[float] = None
    turnover: Optional[float] = None
    estimated_fees_pct: Optional[float] = None
    estimated_slippage_pct: Optional[float] = None
    implementation_shortfall_pct: Optional[float] = None
    rejected_trades: int = 0
    reject_reason: Optional[str] = None
    status: str = "completed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WalkForwardResult(SQLModel, table=True):
    __tablename__ = "walk_forward_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    strategy_id: str = Field(index=True)
    window_index: int
    train_start: Optional[str] = None
    train_end: Optional[str] = None
    test_start: Optional[str] = None
    test_end: Optional[str] = None
    train_metrics: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    test_metrics: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    parameters_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    status: str = "completed"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PositionEnrichedState(SQLModel, table=True):
    """Persisted enriched position state after backfill."""

    __tablename__ = "position_enriched_states"
    broker_symbol: str = Field(primary_key=True)
    state_json: dict = Field(sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyCandidate(SQLModel, table=True):
    __tablename__ = "strategy_candidates"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    parameter_set_id: Optional[str] = None
    run_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="research_only", index=True)
    promotion_stage: str = "research_only"
    metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    rejection_reason: Optional[str] = None
    evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    human_approved: bool = False
    human_approved_at: Optional[datetime] = None
    proposed_by: str = "research_lab"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


engine = create_engine(settings.resolve_database_url(), echo=False)


def _migrate_columns() -> None:
    """Add columns introduced after initial deploy (idempotent)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)

    if insp.has_table("symbol_candidates"):
        sym_cols = {c["name"] for c in insp.get_columns("symbol_candidates")}
        with engine.begin() as conn:
            if "asset_class" not in sym_cols:
                conn.execute(text("ALTER TABLE symbol_candidates ADD COLUMN asset_class VARCHAR DEFAULT 'stock'"))
            if "spread_display" not in sym_cols:
                conn.execute(text("ALTER TABLE symbol_candidates ADD COLUMN spread_display VARCHAR"))

    if insp.has_table("strategy_states"):
        state_cols = {c["name"] for c in insp.get_columns("strategy_states")}
        with engine.begin() as conn:
            if "status_reason" not in state_cols:
                conn.execute(text("ALTER TABLE strategy_states ADD COLUMN status_reason VARCHAR"))

    if insp.has_table("strategy_signals"):
        sig_cols = {c["name"] for c in insp.get_columns("strategy_signals")}
        with engine.begin() as conn:
            if "asset_class" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN asset_class VARCHAR DEFAULT 'stock'"))
            if "side" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN side VARCHAR DEFAULT 'hold'"))
            if "confidence" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN confidence FLOAT DEFAULT 0"))
            if "status" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN status VARCHAR DEFAULT 'generated'"))
            if "stop_loss" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN stop_loss FLOAT"))
            if "take_profit" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN take_profit FLOAT"))
            if "cycle_run_id" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN cycle_run_id VARCHAR"))
            if "signal_type" not in sig_cols:
                conn.execute(text("ALTER TABLE strategy_signals ADD COLUMN signal_type VARCHAR DEFAULT 'entry'"))

    if insp.has_table("blocked_trades"):
        bt_cols = {c["name"] for c in insp.get_columns("blocked_trades")}
        with engine.begin() as conn:
            for col, typ in [
                ("block_reason_code", "VARCHAR"),
                ("human_reason", "VARCHAR"),
                ("risk_rule", "VARCHAR"),
                ("evidence_json", "TEXT"),
                ("risk_engine_result", "TEXT"),
                ("signal_id", "INTEGER"),
                ("cycle_run_id", "VARCHAR"),
            ]:
                if col not in bt_cols:
                    conn.execute(text(f"ALTER TABLE blocked_trades ADD COLUMN {col} {typ}"))

    if insp.has_table("ai_reviews"):
        ai_cols = {c["name"] for c in insp.get_columns("ai_reviews")}
        with engine.begin() as conn:
            if "review_status" not in ai_cols:
                conn.execute(text("ALTER TABLE ai_reviews ADD COLUMN review_status VARCHAR DEFAULT 'success'"))

    if insp.has_table("broker_errors"):
        be_cols = {c["name"] for c in insp.get_columns("broker_errors")}
        with engine.begin() as conn:
            if "cycle_run_id" not in be_cols:
                conn.execute(text("ALTER TABLE broker_errors ADD COLUMN cycle_run_id VARCHAR"))

    if insp.has_table("orders"):
        ord_cols = {c["name"] for c in insp.get_columns("orders")}
        with engine.begin() as conn:
            for col, typ in [
                ("broker_client_order_id", "VARCHAR"),
                ("cycle_run_id", "VARCHAR"),
                ("signal_id", "INTEGER"),
            ]:
                if col not in ord_cols:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {col} {typ}"))

    if insp.has_table("lesson_nodes"):
        ln_cols = {c["name"] for c in insp.get_columns("lesson_nodes")}
        with engine.begin() as conn:
            for col, typ, default in [
                ("category", "VARCHAR", "'trading_memory'"),
                ("status", "VARCHAR", "'active'"),
                ("visible_in_graph", "BOOLEAN", "true"),
                ("visible_to_ai", "BOOLEAN", "true"),
                ("can_influence_ranking", "BOOLEAN", "true"),
                ("human_review_status", "VARCHAR", "'pending'"),
                ("archive_reason", "VARCHAR", None),
                ("deleted_at", "TIMESTAMP", None),
                ("deleted_by", "VARCHAR", None),
            ]:
                if col not in ln_cols:
                    ddl = f"ALTER TABLE lesson_nodes ADD COLUMN {col} {typ}"
                    if default is not None:
                        ddl += f" DEFAULT {default}"
                    conn.execute(text(ddl))

    if insp.has_table("historical_data_coverage"):
        cov_cols = {c["name"] for c in insp.get_columns("historical_data_coverage")}
        with engine.begin() as conn:
            for col, typ, default in [
                ("requested_start_date", "VARCHAR", None),
                ("requested_end_date", "VARCHAR", None),
                ("actual_start_date", "VARCHAR", None),
                ("actual_end_date", "VARCHAR", None),
                ("data_is_recent", "BOOLEAN", "true"),
                ("data_staleness_days", "INTEGER", None),
                ("date_warning", "VARCHAR", None),
            ]:
                if col not in cov_cols:
                    ddl = f"ALTER TABLE historical_data_coverage ADD COLUMN {col} {typ}"
                    if default is not None:
                        ddl += f" DEFAULT {default}"
                    conn.execute(text(ddl))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_columns()


def get_session():
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
