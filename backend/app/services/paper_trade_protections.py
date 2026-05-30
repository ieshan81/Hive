"""Deterministic trade protections — paper-only, entry-gating.

Design concept is inspired by Freqtrade's protection plugins (MaxDrawdown,
StoplossGuard, LowProfitPairs, CooldownPeriod) but **nothing here imports or
depends on Freqtrade** — these are independent, plain-Python, deterministic
checks adapted to Caged Hive Quant's data model.

All protections only ever *block new entries*. Exits, stop-losses, invalidation
exits, emergency exits and the kill switch are never affected by this module.
Nothing here places, cancels, or mutates an order — it is pure evaluation.

The public surface is split so it stays unit-testable without a live DB:

* pure decision functions (``*_protection`` / ``*_guard``) take plain numbers and
  return a :class:`ProtectionResult`;
* ``collect_protection_context`` reads the DB defensively (fail-open: missing
  data degrades to "no block" with a warning, never a crash), and
* ``run_all_protections`` runs the configured guards in order and returns the
  first block (or a clean pass).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select


# ─────────────────────────────────────────────────────────────────────────
# Result + config
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ProtectionResult:
    blocked: bool = False
    code: Optional[str] = None
    reason: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# Conservative defaults. An operator may tune these via
# ``autonomous_paper_learning.protections.*`` config (operator-gated); they are
# protections, not trade-count caps, and they only ever block *new entries*.
PROTECTION_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    # MaxDrawdownProtection
    "max_drawdown_block_pct": 12.0,
    # StoplossGuard
    "stoploss_guard_lookback_hours": 6.0,
    "stoploss_guard_max_stops": 3,
    # LowProfitSymbolGuard
    "low_profit_min_trades": 3,
    "low_profit_net_threshold_usd": 0.0,
    "low_profit_cooldown_hours": 12.0,
    # CooldownAfterExit
    "cooldown_after_exit_minutes": 30,
    "cooldown_strong_signal_score": 0.80,
    # ChurnGuard
    "churn_lookback_hours": 6.0,
    "churn_max_flat_trades": 4,
    "churn_required_edge_after_cost_bps": 40.0,
}


def protections_config(config: dict) -> dict[str, Any]:
    apl = (config or {}).get("autonomous_paper_learning") or {}
    raw = apl.get("protections") or {}
    merged = dict(PROTECTION_DEFAULTS)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if v is not None})
    return merged


def _num(v: Any, fallback: float = 0.0) -> float:
    try:
        n = float(v)
        return n if n == n else fallback  # NaN guard
    except (TypeError, ValueError):
        return fallback


# ─────────────────────────────────────────────────────────────────────────
# Pure decision functions (unit-testable, no DB)
# ─────────────────────────────────────────────────────────────────────────
def max_drawdown_protection(drawdown_pct: float, block_pct: float) -> ProtectionResult:
    """Block new entries when drawdown from peak meets/exceeds the threshold.

    Exits are unaffected. ``drawdown_pct`` is a positive magnitude (e.g. 8.0 == 8% down)."""
    dd = abs(_num(drawdown_pct))
    if block_pct > 0 and dd >= block_pct:
        return ProtectionResult(
            True,
            "MAX_DRAWDOWN_PROTECTION",
            f"Drawdown {dd:.2f}% ≥ block threshold {block_pct:.2f}% — new entries paused (exits allowed)",
            {"drawdown_pct": dd, "block_pct": block_pct},
        )
    return ProtectionResult(evidence={"drawdown_pct": dd, "block_pct": block_pct})


def stoploss_guard(recent_stop_exits: int, max_stops: int, lookback_hours: float) -> ProtectionResult:
    """Block new entries after too many stop-loss exits in the lookback window."""
    if max_stops > 0 and recent_stop_exits >= max_stops:
        return ProtectionResult(
            True,
            "STOPLOSS_GUARD",
            f"{recent_stop_exits} stop-loss exits in {lookback_hours:g}h ≥ {max_stops} — entries paused",
            {"recent_stop_exits": recent_stop_exits, "max_stops": max_stops, "lookback_hours": lookback_hours},
        )
    return ProtectionResult(evidence={"recent_stop_exits": recent_stop_exits, "max_stops": max_stops})


def low_profit_symbol_guard(
    symbol: str,
    symbol_net_pnl_usd: float,
    symbol_trade_count: int,
    min_trades: int,
    net_threshold_usd: float,
) -> ProtectionResult:
    """Cool down a symbol whose recent realized net (after fees) is at/below threshold."""
    if symbol_trade_count >= max(1, min_trades) and _num(symbol_net_pnl_usd) <= net_threshold_usd:
        return ProtectionResult(
            True,
            "LOW_PROFIT_SYMBOL_COOLDOWN",
            f"{symbol} net {symbol_net_pnl_usd:+.2f} over {symbol_trade_count} recent trades ≤ "
            f"{net_threshold_usd:+.2f} — cooled down",
            {
                "symbol": symbol,
                "symbol_net_pnl_usd": _num(symbol_net_pnl_usd),
                "symbol_trade_count": symbol_trade_count,
                "net_threshold_usd": net_threshold_usd,
            },
        )
    return ProtectionResult(evidence={"symbol": symbol, "symbol_net_pnl_usd": _num(symbol_net_pnl_usd)})


def cooldown_after_exit(
    symbol: str,
    minutes_since_last_exit: Optional[float],
    cooldown_minutes: float,
    signal_score: Optional[float],
    strong_signal_score: float,
) -> ProtectionResult:
    """Delay re-entry into a just-exited symbol unless the signal is exceptionally strong."""
    if minutes_since_last_exit is None:
        return ProtectionResult(evidence={"symbol": symbol, "minutes_since_last_exit": None})
    within = minutes_since_last_exit < cooldown_minutes
    strong = signal_score is not None and _num(signal_score) >= strong_signal_score
    if within and not strong:
        return ProtectionResult(
            True,
            "COOLDOWN_AFTER_EXIT",
            f"{symbol} exited {minutes_since_last_exit:.0f}m ago (< {cooldown_minutes:g}m) and signal "
            f"{(_num(signal_score) if signal_score is not None else 0):.2f} < {strong_signal_score:.2f}",
            {
                "symbol": symbol,
                "minutes_since_last_exit": minutes_since_last_exit,
                "cooldown_minutes": cooldown_minutes,
                "signal_score": signal_score,
            },
        )
    return ProtectionResult(evidence={"symbol": symbol, "minutes_since_last_exit": minutes_since_last_exit})


def churn_guard(
    recent_flat_trades: int,
    max_flat_trades: int,
    edge_after_cost_bps: Optional[float],
    required_edge_bps: float,
) -> ProtectionResult:
    """When recent activity is churny (many near-flat / fee-negative exits), require a stronger edge."""
    if max_flat_trades > 0 and recent_flat_trades >= max_flat_trades:
        edge = _num(edge_after_cost_bps, fallback=-1e9) if edge_after_cost_bps is not None else None
        if edge is None or edge < required_edge_bps:
            return ProtectionResult(
                True,
                "CHURN_GUARD",
                f"{recent_flat_trades} near-flat/fee-negative trades recently — require edge ≥ "
                f"{required_edge_bps:g}bps (have {('n/a' if edge is None else f'{edge:.0f}bps')})",
                {
                    "recent_flat_trades": recent_flat_trades,
                    "max_flat_trades": max_flat_trades,
                    "edge_after_cost_bps": edge_after_cost_bps,
                    "required_edge_bps": required_edge_bps,
                },
            )
    return ProtectionResult(evidence={"recent_flat_trades": recent_flat_trades})


# ─────────────────────────────────────────────────────────────────────────
# DB context collection (defensive / fail-open)
# ─────────────────────────────────────────────────────────────────────────
@dataclass
class ProtectionContext:
    symbol: str = ""
    drawdown_pct: float = 0.0
    recent_stop_exits: int = 0
    symbol_net_pnl_usd: float = 0.0
    symbol_trade_count: int = 0
    minutes_since_last_exit: Optional[float] = None
    recent_flat_trades: int = 0
    signal_score: Optional[float] = None
    edge_after_cost_bps: Optional[float] = None
    warnings: list[str] = field(default_factory=list)


def collect_protection_context(
    session: Session,
    config: dict,
    *,
    symbol: str,
    drawdown_pct: float = 0.0,
    signal_score: Optional[float] = None,
    edge_after_cost_bps: Optional[float] = None,
) -> ProtectionContext:
    """Read recent paper-trade telemetry for the protections. Fail-open: any read
    error degrades the affected field to a neutral value with a warning, never raises."""
    cfg = protections_config(config)
    ctx = ProtectionContext(
        symbol=symbol,
        drawdown_pct=abs(_num(drawdown_pct)),
        signal_score=signal_score,
        edge_after_cost_bps=edge_after_cost_bps,
    )

    now = datetime.utcnow()

    # Realized exit outcomes (PnL, fees, exit_reason) live on PaperExperimentOutcome —
    # ExecutionLog rows do NOT carry realized PnL/exit_reason, so reading them made every
    # exit look fee-negative and spuriously tripped the churn / low-profit guards. Read the
    # real outcomes here, and only count a trade as flat/fee-negative when a realized figure
    # actually exists (missing data -> not counted, so guards never block on absence).
    sym_norm = (symbol or "").upper().replace("/", "")
    try:
        from app.database import PaperExperimentOutcome

        since = now - timedelta(hours=_num(cfg["stoploss_guard_lookback_hours"], 6.0))
        rows = session.exec(
            select(PaperExperimentOutcome).where(PaperExperimentOutcome.created_at >= since)
        ).all()
        stops = 0
        last_exit_dt: Optional[datetime] = None
        flat = 0
        sym_net = 0.0
        sym_trades = 0
        for r in rows:
            reason = str(getattr(r, "exit_reason", "") or "").lower()
            if any(k in reason for k in ("stop", "invalidat", "emergency")):
                stops += 1
            realized_raw = getattr(r, "realized_pnl", None)
            net = _num(realized_raw, 0.0) - _num(getattr(r, "fees_estimated", None), 0.0)
            if realized_raw is not None and net <= 0:
                flat += 1
            if str(getattr(r, "symbol", "") or "").upper().replace("/", "") == sym_norm:
                if realized_raw is not None:
                    sym_net += net
                    sym_trades += 1
                cat = getattr(r, "created_at", None)
                if isinstance(cat, datetime) and (last_exit_dt is None or cat > last_exit_dt):
                    last_exit_dt = cat
        ctx.recent_stop_exits = stops
        ctx.recent_flat_trades = flat
        ctx.symbol_net_pnl_usd = sym_net
        ctx.symbol_trade_count = sym_trades
        if last_exit_dt is not None:
            ctx.minutes_since_last_exit = max(0.0, (now - last_exit_dt).total_seconds() / 60.0)
    except Exception as exc:  # fail-open
        ctx.warnings.append(f"protection_context_degraded:{type(exc).__name__}")

    return ctx


def run_all_protections(ctx: ProtectionContext, config: dict) -> ProtectionResult:
    """Run every protection in order; return the first block, or a clean pass.

    Order: drawdown → stoploss guard → low-profit symbol → cooldown-after-exit → churn."""
    cfg = protections_config(config)
    if not bool(cfg.get("enabled", True)):
        return ProtectionResult(warnings=["protections_disabled"])

    checks = [
        max_drawdown_protection(ctx.drawdown_pct, _num(cfg["max_drawdown_block_pct"], 12.0)),
        stoploss_guard(
            ctx.recent_stop_exits,
            int(cfg["stoploss_guard_max_stops"]),
            _num(cfg["stoploss_guard_lookback_hours"], 6.0),
        ),
        low_profit_symbol_guard(
            ctx.symbol,
            ctx.symbol_net_pnl_usd,
            ctx.symbol_trade_count,
            int(cfg["low_profit_min_trades"]),
            _num(cfg["low_profit_net_threshold_usd"], 0.0),
        ),
        cooldown_after_exit(
            ctx.symbol,
            ctx.minutes_since_last_exit,
            _num(cfg["cooldown_after_exit_minutes"], 30.0),
            ctx.signal_score,
            _num(cfg["cooldown_strong_signal_score"], 0.80),
        ),
        churn_guard(
            ctx.recent_flat_trades,
            int(cfg["churn_max_flat_trades"]),
            ctx.edge_after_cost_bps,
            _num(cfg["churn_required_edge_after_cost_bps"], 40.0),
        ),
    ]
    for res in checks:
        if res.blocked:
            res.warnings = list(ctx.warnings)
            return res
    return ProtectionResult(warnings=list(ctx.warnings), evidence={"protections": "clean"})
