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
