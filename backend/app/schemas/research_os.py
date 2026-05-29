"""Research OS API contracts.

These schemas validate AI/operator proposals before persistence. They are not
execution permissions; the deterministic execution cage remains the only order
path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


AssetClass = Literal["crypto", "stock", "both"]
StrategyFamily = Literal[
    "momentum",
    "mean_reversion",
    "breakout",
    "pullback_push_pull",
    "volatility_breakout",
    "sentiment_assisted",
    "trend_following",
    "statistical_placeholder",
]


class LogicBlock(BaseModel):
    kind: str = Field(min_length=1)
    formula: str = Field(default="")
    parameters: dict[str, Any] = Field(default_factory=dict)
    explanation: str = Field(default="")


class FeatureRequirement(BaseModel):
    name: str
    source: str = "cached_market_data"
    min_rows: int = 0
    freshness_seconds: Optional[int] = None
    required: bool = True


class StrategySpec(BaseModel):
    strategy_id: str = Field(min_length=3)
    name: str = Field(min_length=3)
    version: str = "1.0.0"
    family: StrategyFamily
    asset_classes: list[AssetClass]
    timeframes: list[str]
    entry_logic: LogicBlock
    exit_logic: LogicBlock
    risk_logic: LogicBlock
    sizing_logic: LogicBlock
    required_features: list[FeatureRequirement] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    source: str = "operator"
    status: str = "draft"
    notes: Optional[str] = None

    @field_validator("strategy_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("strategy_id may contain only letters, numbers, dashes, and underscores")
        return cleaned


class BacktestRequest(BaseModel):
    strategy_id: str
    symbols: list[str]
    timeframe: str = "5Min"
    lookback_days: int = Field(default=30, ge=1, le=365)
    parameters: dict[str, Any] = Field(default_factory=dict)
    fee_model: dict[str, Any] = Field(default_factory=dict)
    slippage_model: dict[str, Any] = Field(default_factory=dict)


class BacktestResult(BaseModel):
    run_id: str
    strategy_id: str
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class OptimizationRequest(BaseModel):
    strategy_id: str
    objective: str = "expectancy"
    optimizer_type: Literal["grid", "random", "optuna"] = "grid"
    parameter_grid: dict[str, list[Any]] = Field(default_factory=dict)
    max_trials: int = Field(default=12, ge=1, le=200)


class RiskAuditReportSchema(BaseModel):
    report_id: str
    strategy_id: str
    pass_fail: Literal["pass", "fail", "warn", "unknown"]
    risk_score: float = Field(ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)
    veto_reason: Optional[str] = None


class PromotionProposalSchema(BaseModel):
    strategy_id: str
    from_stage: str
    to_stage: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    proposed_by_agent: Optional[str] = None
    requires_human_approval: bool = True


class MemoryEntry(BaseModel):
    memory_type: str
    symbol: Optional[str] = None
    strategy_id: Optional[str] = None
    lesson: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: str = "candidate"


class AgentOutput(BaseModel):
    graph_run_id: str
    agent_name: str
    node_name: str
    status: Literal["queued", "running", "complete", "failed", "blocked"]
    output: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class CodeProposal(BaseModel):
    title: str
    description: str = ""
    proposed_by_agent: str = "research_os"
    affected_files: list[str] = Field(default_factory=list)
    diff_text: str = ""
    tests_required: list[str] = Field(default_factory=list)
    risk_assessment: dict[str, Any] = Field(default_factory=dict)


class TradingViewSignalOverlay(BaseModel):
    symbol: str
    timeframe: str = "5Min"
    signal_type: str = "overlay"
    levels: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    no_trade_blockers: list[str] = Field(default_factory=list)


class LiveFlagChangeRequest(BaseModel):
    requested_flags: dict[str, Any] = Field(default_factory=dict)
    actor_type: str = "operator"
    requested_by: str = "operator"
    confirmation_phrase: str = ""

