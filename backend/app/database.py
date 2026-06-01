from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session
from sqlalchemy import Column, JSON, LargeBinary, Text

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
    system_validation_status: str = Field(default="pending", index=True)
    system_validated_at: Optional[datetime] = None
    system_validator_rule: Optional[str] = None
    archive_reason: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    pattern_key: Optional[str] = Field(default=None, index=True)
    occurrence_count: int = 1
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    tags: Optional[list] = Field(default=None, sa_column=Column(JSON))
    unsupported_claim: bool = False
    is_consolidated: bool = Field(default=False, index=True)
    consolidated_into_memory_id: Optional[int] = Field(default=None, index=True)
    source_memory_ids_json: Optional[list] = Field(default=None, sa_column=Column(JSON))
    retention_until: Optional[datetime] = None
    importance_score: float = Field(default=0.5)
    memory_level: str = Field(default="raw_experience", index=True)  # raw_experience|pattern_memory|consolidated_lesson|core_ai_lesson
    memory_scope: str = Field(default="strategy", index=True)  # symbol|strategy|portfolio|system|ai
    strength: float = Field(default=0.5)
    last_confirmed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    reset_epoch_id: Optional[str] = Field(default=None, index=True)


class MemoryPolicyConfig(SQLModel, table=True):
    __tablename__ = "memory_policy_config"
    id: Optional[int] = Field(default=1, primary_key=True)
    policy_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemeSpikeEvaluation(SQLModel, table=True):
    __tablename__ = "meme_spike_evaluations"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    spike_detected: bool = False
    momentum_quality: Optional[str] = None
    manipulation_risk: str = Field(default="low", index=True)
    entry_quality: Optional[str] = None
    suggested_action: str = Field(default="observe_only")
    reason_codes_json: Optional[list] = Field(default=None, sa_column=Column(JSON))
    metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SettingsActionAudit(SQLModel, table=True):
    __tablename__ = "settings_actions_audit"
    id: Optional[int] = Field(default=None, primary_key=True)
    action: str = Field(index=True)
    actor: str = "operator"
    broker_mode: str = "paper"
    paper_broker: bool = True
    live_trading_locked: bool = True
    live_orders_enabled: bool = False
    details_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DiagnosticExportJob(SQLModel, table=True):
    """Persistent diagnostic export job metadata and optional ZIP payload."""

    __tablename__ = "diagnostic_export_jobs"
    job_id: str = Field(primary_key=True, index=True)
    status: str = Field(default="queued", index=True)  # queued|running|complete|failed
    progress_pct: int = 0
    # Human-readable step shown in the Reports UI while running.
    current_step: Optional[str] = Field(default=None)
    last_completed_file: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    filename: Optional[str] = None
    file_count: int = 0
    failed_sections: Optional[list] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = None
    storage_path: Optional[str] = None
    zip_size_bytes: int = 0
    zip_bytes: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))


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


# --- Strategy Promotion Pipeline / Living Registry ---

class StrategyRegistry(SQLModel, table=True):
    __tablename__ = "strategy_registry"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True, unique=True)
    name: str
    family: str = Field(index=True)
    version: str = "1.0.0"
    code_hash: Optional[str] = None
    asset_class: str = "crypto"
    symbols: list = Field(default_factory=list, sa_column=Column(JSON))
    timeframe: str = "1h"
    author_type: str = "built_in"
    parameter_schema_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    active_parameters_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    current_stage: str = Field(default="research_only", index=True)
    previous_stage: Optional[str] = None
    current_score: Optional[float] = None
    confidence: str = "low"
    risk_tier: str = "micro_safe"
    allowed_capital_usd: Optional[float] = None
    allowed_risk_pct: Optional[float] = None
    can_trade_paper: bool = False
    can_trade_live: bool = False
    live_locked: bool = True
    quarantine_status: Optional[str] = None
    data_quality_score: Optional[float] = None
    cost_sensitivity_score: Optional[float] = None
    overfit_risk_score: Optional[float] = None
    latest_backtest_run_id: Optional[str] = None
    latest_walk_forward_id: Optional[str] = None
    latest_paper_performance_id: Optional[str] = None
    latest_rejection_id: Optional[str] = None
    latest_validation_id: Optional[str] = None
    memory_count: int = 0
    validated_memory_count: int = 0
    pending_memory_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_reviewed_at: Optional[datetime] = None


class StrategyLifecycleEvent(SQLModel, table=True):
    __tablename__ = "strategy_lifecycle_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    from_stage: str
    to_stage: str
    reason_code: str
    reason_text: str
    evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    decided_by: str = "validation_gate"
    ai_advisory_payload_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyValidationResult(SQLModel, table=True):
    __tablename__ = "strategy_validation_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    gate_name: str
    target_stage: str
    passed: bool
    metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    thresholds_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    failure_reasons_json: Optional[list] = Field(default=None, sa_column=Column(JSON))
    warning_reasons_json: Optional[list] = Field(default=None, sa_column=Column(JSON))
    data_freshness_ok: bool = False
    sample_size_ok: bool = False
    cost_realism_ok: bool = False
    risk_ok: bool = False
    broker_ok: bool = False
    reconciliation_ok: bool = False
    memory_ok: bool = False
    portfolio_ok: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyScorecard(SQLModel, table=True):
    __tablename__ = "strategy_scorecards"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    as_of: datetime = Field(default_factory=datetime.utcnow)
    expectancy_net: Optional[float] = None
    profit_factor_net: Optional[float] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    psr: Optional[float] = None
    dsr: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    sample_size: Optional[int] = None
    walk_forward_pass_rate: Optional[float] = None
    cost_to_edge_ratio: Optional[float] = None
    cost_drag_pct: Optional[float] = None
    paper_perf_30d: Optional[float] = None
    live_perf_30d: Optional[float] = None
    correlation_to_active_book: Optional[float] = None
    regime_fit_score: Optional[float] = None
    degradation_30d: Optional[float] = None
    memory_evidence_score: Optional[float] = None
    composite_score: Optional[float] = None
    confidence: str = "low"
    recommended_action: str = "hold"
    promote_allowed: bool = False
    rejection_reason: Optional[str] = None
    data_warning: Optional[str] = None
    parameter_variation_warning: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AlphaScorecard(SQLModel, table=True):
    """Symbol-level autonomous alpha evidence.

    This complements ``StrategyScorecard`` instead of replacing it. Existing
    strategy scorecards are strategy-level; this table tracks whether a concrete
    symbol/strategy/timeframe has enough research evidence to govern paper entry.
    """

    __tablename__ = "alpha_scorecards"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    normalized_symbol: str = Field(index=True)
    asset_class: str = Field(default="crypto", index=True)
    strategy_family: str = Field(index=True)
    strategy_id: str = Field(index=True)
    timeframe: str = "5Min"
    current_stage: str = Field(default="unproven", index=True)
    sample_size: int = 0
    backtest_count: int = 0
    walk_forward_count: int = 0
    win_rate: Optional[float] = None
    expectancy: Optional[float] = None
    profit_factor: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    sharpe_if_available: Optional[float] = None
    avg_trade_duration: Optional[float] = None
    average_win: Optional[float] = None
    average_loss: Optional[float] = None
    payoff_ratio: Optional[float] = None
    cost_bps: Optional[float] = None
    spread_bps: Optional[float] = None
    slippage_bps: Optional[float] = None
    fee_bps: Optional[float] = None
    edge_after_cost_bps: Optional[float] = None
    recent_paper_trade_count: int = 0
    recent_paper_pnl: float = 0.0
    recent_churn_count: int = 0
    recent_loss_cooldown_until: Optional[datetime] = None
    data_freshness_status: str = "unknown"
    bar_count: int = 0
    quote_freshness: str = "unknown"
    verdict: str = Field(default="unproven", index=True)
    blocker_reasons_json: list = Field(default_factory=list, sa_column=Column(JSON))
    promotion_reason: Optional[str] = None
    last_backtest_run_id: Optional[str] = Field(default=None, index=True)
    last_walk_forward_run_id: Optional[str] = Field(default=None, index=True)
    evidence_ids_json: list = Field(default_factory=list, sa_column=Column(JSON))
    autonomous_generated: bool = True
    best_session: Optional[str] = Field(default=None, index=True)
    worst_session: Optional[str] = None
    session_sample_size: int = 0
    session_win_rate: Optional[float] = None
    session_expectancy: Optional[float] = None
    session_profit_factor: Optional[float] = None
    session_edge_after_cost_bps: Optional[float] = None
    london_session_metrics_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    new_york_session_metrics_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    london_new_york_overlap_metrics_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    low_liquidity_session_warning: Optional[str] = None
    scorecard_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyPromotionRule(SQLModel, table=True):
    __tablename__ = "strategy_promotion_rules"
    id: Optional[int] = Field(default=None, primary_key=True)
    profile: str = Field(default="micro_account_safe", index=True)
    rule_key: str
    threshold_value_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    weight: float = 1.0
    asset_class: Optional[str] = None
    strategy_family: Optional[str] = None
    stage_from: str
    stage_to: str
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyRejection(SQLModel, table=True):
    __tablename__ = "strategy_rejections"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    gate_name: str
    failure_codes_json: list = Field(default_factory=list, sa_column=Column(JSON))
    permanent: bool = False
    allow_retry_after: Optional[datetime] = None
    rationale: str
    evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyRetirement(SQLModel, table=True):
    __tablename__ = "strategy_retirements"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    trigger_code: str
    performance_snapshot_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    rationale: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyMemoryLink(SQLModel, table=True):
    __tablename__ = "strategy_memory_links"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    memory_id: int = Field(index=True)
    memory_type: str
    memory_status: str = Field(default="pending", index=True)
    visible_to_ai: bool = True
    can_influence_ranking: bool = False
    validator_rule: Optional[str] = None
    validation_evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    validated_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyConflict(SQLModel, table=True):
    __tablename__ = "strategy_conflicts"
    id: Optional[int] = Field(default=None, primary_key=True)
    winner_strategy_id: Optional[str] = None
    loser_strategy_id: Optional[str] = None
    symbol: str
    side: str
    signal_timestamp: Optional[datetime] = None
    resolution: str
    evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyAllocation(SQLModel, table=True):
    __tablename__ = "strategy_allocations"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    as_of: datetime = Field(default_factory=datetime.utcnow)
    risk_budget_pct: Optional[float] = None
    max_position_usd: Optional[float] = None
    max_open_positions: int = 1
    kelly_fraction: Optional[float] = None
    daily_entry_limit: int = 3
    strategy_entry_limit: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyEligibilityWindow(SQLModel, table=True):
    __tablename__ = "strategy_eligibility_windows"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    stage: str = "live_candidate"
    eligibility_start_at_utc: datetime
    earliest_promote_at_utc: datetime
    latest_decision_at_utc: datetime
    valid_observation_count: int = 0
    soft_warning_count: int = 0
    hard_block_reason: Optional[str] = None
    eligibility_health: str = "clean"
    eligibility_window_version: int = 1
    material_config_changed: bool = False
    maintenance_pass: bool = False
    capacity_pass: bool = False
    correlation_pass: bool = False
    decision: Optional[str] = None
    decision_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None


class PaperExperimentConfig(SQLModel, table=True):
    __tablename__ = "paper_experiment_config"
    id: Optional[int] = Field(default=None, primary_key=True)
    profile: str = Field(default="aggressive_paper_learning", index=True)
    config_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    mode_enabled: bool = False
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PaperExperimentDecision(SQLModel, table=True):
    __tablename__ = "paper_experiment_decisions"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    signal_id: Optional[int] = Field(default=None, index=True)
    symbol: str = Field(index=True)
    side: str = "buy"
    requested_notional: float = 0.0
    approved_notional: float = 0.0
    decision: str = Field(index=True)
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    risk_snapshot_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    execution_order_id: Optional[int] = Field(default=None, index=True)
    execution_status: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PaperExperimentRun(SQLModel, table=True):
    __tablename__ = "paper_experiment_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    symbol: str
    status: str = "pending"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None


class PaperExperimentOutcome(SQLModel, table=True):
    __tablename__ = "paper_experiment_outcomes"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    symbol: str
    entry_order_id: Optional[int] = None
    exit_order_id: Optional[int] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    qty: Optional[float] = None
    realized_pnl: Optional[float] = None
    fees_estimated: Optional[float] = None
    hold_minutes: Optional[float] = None
    exit_reason: Optional[str] = None
    lesson_created: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyChangeProposal(SQLModel, table=True):
    __tablename__ = "strategy_change_proposals"
    id: Optional[int] = Field(default=None, primary_key=True)
    proposal_type: str = Field(index=True)
    strategy_id: str = Field(index=True)
    patch_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    reason: str
    memory_evidence_ids: Optional[list] = Field(default=None, sa_column=Column(JSON))
    backtest_run_id: Optional[str] = None
    risk_note: Optional[str] = None
    status: str = Field(default="proposed", index=True)
    requires_operator_approval: bool = True
    expected_risk: Optional[str] = None
    proposed_by: str = "confidence_engine"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FastTrainingLease(SQLModel, table=True):
    """Singleton-style lease row to prevent overlapping fast-training runs."""

    __tablename__ = "fast_training_leases"
    lease_key: str = Field(primary_key=True, default="fast_training_run")
    holder_id: Optional[str] = None
    acquired_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_completed_at: Optional[datetime] = None
    last_result_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))


class SystemValidationAudit(SQLModel, table=True):
    __tablename__ = "system_validation_audit"
    id: Optional[int] = Field(default=None, primary_key=True)
    actor: str = "gate"
    action: str
    target_strategy_id: Optional[str] = None
    inputs_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    decision: str
    reasoning: Optional[str] = None
    deterministic_seed: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


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


class StrategySpecRecord(SQLModel, table=True):
    """Research OS strategy contract.

    Existing StrategyDefinition remains the lightweight registry/library table.
    This record stores the richer, versioned StrategySpec payload used by the
    Research OS without replacing the current strategy registry.
    """

    __tablename__ = "strategy_specs"
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: str = Field(index=True)
    name: str
    version: str = "1.0.0"
    family: str = Field(index=True)
    asset_classes: list = Field(default_factory=list, sa_column=Column(JSON))
    timeframes: list = Field(default_factory=list, sa_column=Column(JSON))
    entry_logic_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    exit_logic_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    risk_logic_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    sizing_logic_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    required_features_json: list = Field(default_factory=list, sa_column=Column(JSON))
    constraints_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    source: str = "research_os"
    status: str = Field(default="draft", index=True)
    created_by: str = "operator"
    fingerprint: Optional[str] = Field(default=None, index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ResearchJob(SQLModel, table=True):
    __tablename__ = "research_jobs"
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True, unique=True)
    job_type: str = Field(index=True)
    status: str = Field(default="queued", index=True)
    priority: int = 50
    requested_by: str = "operator"
    agent_name: Optional[str] = Field(default=None, index=True)
    input_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    output_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error: Optional[str] = None
    progress_pct: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OptimizationRun(SQLModel, table=True):
    __tablename__ = "optimization_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    optimization_id: str = Field(index=True, unique=True)
    strategy_id: str = Field(index=True)
    optimizer_type: str = "grid"
    objective: str = "expectancy"
    trials_count: int = 0
    tried_params_json: Optional[list] = Field(default=None, sa_column=Column(JSON))
    best_params_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    best_metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="queued", index=True)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class RiskAuditReport(SQLModel, table=True):
    __tablename__ = "risk_audit_reports"
    id: Optional[int] = Field(default=None, primary_key=True)
    report_id: str = Field(index=True, unique=True)
    strategy_id: str = Field(index=True)
    backtest_run_id: Optional[str] = Field(default=None, index=True)
    validation_report_id: Optional[str] = None
    risk_score: float = 0.0
    drawdown_metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    tail_risk_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    liquidity_metrics_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    concentration_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    correlation_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    pass_fail: str = Field(default="unknown", index=True)
    veto_reason: Optional[str] = None
    reasons_json: Optional[list] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AIAgentRun(SQLModel, table=True):
    __tablename__ = "ai_agent_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    graph_run_id: str = Field(index=True)
    agent_name: str = Field(index=True)
    node_name: str = Field(index=True)
    status: str = Field(default="queued", index=True)
    input_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    output_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    tool_calls_json: Optional[list] = Field(default=None, sa_column=Column(JSON))
    cost_estimate: Optional[float] = None
    model_name: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class CodeProposal(SQLModel, table=True):
    __tablename__ = "code_proposals"
    id: Optional[int] = Field(default=None, primary_key=True)
    proposal_id: str = Field(index=True, unique=True)
    title: str
    description: Optional[str] = None
    proposed_by_agent: str = "research_os"
    affected_files_json: list = Field(default_factory=list, sa_column=Column(JSON))
    diff_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    patch_ref: Optional[str] = None
    tests_required_json: list = Field(default_factory=list, sa_column=Column(JSON))
    risk_assessment_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="draft", index=True)
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None


class LiveReadinessReview(SQLModel, table=True):
    __tablename__ = "live_readiness_reviews"
    id: Optional[int] = Field(default=None, primary_key=True)
    stage: str = Field(index=True)
    status: str = Field(default="locked", index=True)
    account_snapshot_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    paper_performance_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    risk_evidence_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    reconciliation_status_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    kill_switch_status_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    approval_required: bool = True
    approved_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TradingViewIntegration(SQLModel, table=True):
    __tablename__ = "tradingview_integrations"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    status: str = Field(default="display_only", index=True)
    webhook_secret_hash: Optional[str] = None
    allowed_actions: list = Field(default_factory=lambda: ["display_overlay"], sa_column=Column(JSON))
    display_config_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    last_event_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TradingViewEvent(SQLModel, table=True):
    __tablename__ = "tradingview_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    integration_id: Optional[int] = Field(default=None, index=True)
    event_type: str = Field(default="signal", index=True)
    payload_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    mapped_signal_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    accepted_for_display: bool = True
    execution_blocked_reason: str = "display_only_execution_blocked"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LiveFlagChangeRequest(SQLModel, table=True):
    __tablename__ = "live_flag_change_requests"
    id: Optional[int] = Field(default=None, primary_key=True)
    requested_by: str = "operator"
    actor_type: str = Field(default="operator", index=True)
    current_flags_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    requested_flags_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="requested", index=True)
    confirmation_phrase_ok: bool = False
    approval_stage: str = "dry_run_required"
    dry_run_result_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    audit_log_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    approved_at: Optional[datetime] = None
    rejected_reason: Optional[str] = None


def _create_db_engine():
    url = settings.resolve_database_url()
    kwargs: dict = {"echo": False}
    if url.startswith("postgresql") or url.startswith("postgres"):
        kwargs.update(
            pool_pre_ping=True,
            pool_size=8,
            max_overflow=12,
            pool_timeout=30,
            pool_recycle=1800,
        )
    return create_engine(url, **kwargs)


engine = _create_db_engine()


def _migrate_columns() -> None:
    """Legacy compatibility only.

    Keep this idempotent and non-destructive for existing Railway databases.
    New schema work should use SQLModel models plus Alembic migrations; avoid
    adding more ad-hoc ALTER TABLE blocks unless a production compatibility
    patch absolutely requires it.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)

    if insp.has_table("symbol_candidates"):
        sym_cols = {c["name"] for c in insp.get_columns("symbol_candidates")}
        with engine.begin() as conn:
            if "asset_class" not in sym_cols:
                conn.execute(text("ALTER TABLE symbol_candidates ADD COLUMN asset_class VARCHAR DEFAULT 'stock'"))
            if "spread_display" not in sym_cols:
                conn.execute(text("ALTER TABLE symbol_candidates ADD COLUMN spread_display VARCHAR"))

    # Diagnostic export job progress fields (Phase 4 — non-destructive).
    if insp.has_table("diagnostic_export_jobs"):
        job_cols = {c["name"] for c in insp.get_columns("diagnostic_export_jobs")}
        with engine.begin() as conn:
            if "current_step" not in job_cols:
                conn.execute(text("ALTER TABLE diagnostic_export_jobs ADD COLUMN current_step VARCHAR"))
            if "last_completed_file" not in job_cols:
                conn.execute(text("ALTER TABLE diagnostic_export_jobs ADD COLUMN last_completed_file VARCHAR"))

    if insp.has_table("alpha_scorecards"):
        alpha_cols = {c["name"] for c in insp.get_columns("alpha_scorecards")}
        with engine.begin() as conn:
            for col, typ, default in [
                ("best_session", "VARCHAR", None),
                ("worst_session", "VARCHAR", None),
                ("session_sample_size", "INTEGER", "0"),
                ("session_win_rate", "FLOAT", None),
                ("session_expectancy", "FLOAT", None),
                ("session_profit_factor", "FLOAT", None),
                ("session_edge_after_cost_bps", "FLOAT", None),
                ("london_session_metrics_json", "JSON", None),
                ("new_york_session_metrics_json", "JSON", None),
                ("london_new_york_overlap_metrics_json", "JSON", None),
                ("low_liquidity_session_warning", "VARCHAR", None),
            ]:
                if col not in alpha_cols:
                    ddl = f"ALTER TABLE alpha_scorecards ADD COLUMN {col} {typ}"
                    if default is not None:
                        ddl += f" DEFAULT {default}"
                    conn.execute(text(ddl))

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
                ("system_validation_status", "VARCHAR", "'pending'"),
                ("system_validated_at", "TIMESTAMP", None),
                ("system_validator_rule", "VARCHAR", None),
                ("archive_reason", "VARCHAR", None),
                ("deleted_at", "TIMESTAMP", None),
                ("deleted_by", "VARCHAR", None),
            ]:
                if col not in ln_cols:
                    ddl = f"ALTER TABLE lesson_nodes ADD COLUMN {col} {typ}"
                    if default is not None:
                        ddl += f" DEFAULT {default}"
                    conn.execute(text(ddl))
            for col, typ, default in [
                ("is_consolidated", "BOOLEAN", "false"),
                ("consolidated_into_memory_id", "INTEGER", None),
                ("source_memory_ids_json", "TEXT", None),
                ("retention_until", "TIMESTAMP", None),
                ("importance_score", "FLOAT", "0.5"),
                ("memory_level", "VARCHAR", "'raw_experience'"),
                ("memory_scope", "VARCHAR", "'strategy'"),
                ("strength", "FLOAT", "0.5"),
                ("last_confirmed_at", "TIMESTAMP", None),
                ("reset_epoch_id", "VARCHAR", None),
            ]:
                if col not in ln_cols:
                    ddl = f"ALTER TABLE lesson_nodes ADD COLUMN {col} {typ}"
                    if default is not None:
                        ddl += f" DEFAULT {default}"
                    conn.execute(text(ddl))

    if insp.has_table("paper_experiment_decisions"):
        ped_cols = {c["name"] for c in insp.get_columns("paper_experiment_decisions")}
        with engine.begin() as conn:
            for col, typ in [
                ("execution_order_id", "INTEGER"),
                ("execution_status", "VARCHAR"),
            ]:
                if col not in ped_cols:
                    conn.execute(text(f"ALTER TABLE paper_experiment_decisions ADD COLUMN {col} {typ}"))

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


class SymbolSpreadState(SQLModel, table=True):
    """Per-symbol spread tracking: entry cooldown (spread-widened rotation) + failed-exit
    escalation. Paper-only telemetry/state; never holds orders or secrets."""

    __tablename__ = "symbol_spread_state"
    symbol: str = Field(primary_key=True)  # normalized, e.g. SOLUSD
    # Entry-side: repeated SPREAD_WIDENED -> cooldown + rotate to next candidate
    spread_widened_count: int = 0
    last_spread_widened_at: Optional[datetime] = None
    spread_cooldown_until: Optional[datetime] = None
    # Exit-side: repeated failed exit attempts -> escalate exit + freeze new entries
    failed_exit_attempts: int = 0
    first_failed_exit_at: Optional[datetime] = None
    last_failed_exit_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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
