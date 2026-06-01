from __future__ import annotations

import copy
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

tmp_db = Path(tempfile.gettempdir()) / f"hive_alpha_verify_{os.getpid()}.db"
try:
    tmp_db.unlink()
except FileNotFoundError:
    pass

os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db.as_posix()}"
os.environ["LIVE_TRADING_ARMED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session  # noqa: E402

from app.database import (  # noqa: E402
    AlphaScorecard,
    HistoricalBar,
    PaperExperimentOutcome,
    ResearchBacktestRun,
    engine,
    init_db,
)
from app.services.config_manager import ConfigManager  # noqa: E402
from app.services.default_config import DEFAULT_CONFIG  # noqa: E402


def session_with_config() -> tuple[Session, dict]:
    init_db()
    session = Session(engine)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.setdefault("execution", {})
    cfg["execution"]["paper_orders_enabled"] = True
    cfg["execution"]["live_orders_enabled"] = False
    cfg["live_trading_enabled"] = False
    cfg.setdefault("promotion", {})["current_stage"] = "PAPER"
    cfg.setdefault("alpha_factory", {})
    cfg["alpha_factory"].update(
        {
            "require_alpha_candidate_for_paper_entry": True,
            "require_alpha_candidate_for_execution": True,
            "min_sample_size": 5,
            "min_profit_factor": 1.05,
            "max_drawdown_pct": 35.0,
            "min_edge_after_cost_bps": 0.0,
            "scheduler_enabled": True,
            "scheduler_interval_minutes": 1,
        }
    )
    ConfigManager(session)._activate(cfg, changed_by="alpha_verify", reason="isolated alpha verifier")
    return session, ConfigManager(session).get_current()


def seed_bars(session: Session, symbol: str = "BTC/USD", n: int = 80) -> None:
    now = datetime.utcnow().replace(second=0, microsecond=0)
    for idx in range(n):
        base = 100.0 + idx * 0.3
        session.add(
            HistoricalBar(
                symbol=symbol,
                asset_class="crypto" if "/" in symbol else "stock",
                timeframe="5Min",
                timestamp=now - timedelta(minutes=5 * (n - idx)),
                open=base,
                high=base + 1.2,
                low=base - 0.8,
                close=base + 0.9,
                volume=1000 + idx,
                source="fixture",
                synthetic=False,
            )
        )
    session.commit()


def seed_backtest(
    session: Session,
    *,
    symbol: str = "BTC/USD",
    strategy_id: str = "crypto_push_pull_baseline",
    expectancy: float = 0.006,
    profit_factor: float = 1.32,
    trades: int = 18,
    run_id: str = "bt_fixture_alpha",
) -> ResearchBacktestRun:
    row = ResearchBacktestRun(
        run_id=run_id,
        strategy_id=strategy_id,
        parameter_set_id="ps_fixture",
        symbols=[symbol],
        status="ok",
        num_trades=trades,
        sample_size=trades,
        metrics_json={
            "num_trades": trades,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "win_rate": 0.58,
            "max_drawdown": 0.04,
            "avg_win": 0.012,
            "avg_loss": -0.007,
            "bars_count": 80,
            "timeframe": "5Min",
            "cost_model": {"round_trip_cost_pct": 0.001, "spread_pct": 0.0003, "slippage_pct": 0.0002, "fee_pct": 0.0},
        },
        cost_model_json={"round_trip_cost_pct": 0.001, "spread_pct": 0.0003, "slippage_pct": 0.0002, "fee_pct": 0.0},
        confidence_label="medium",
        warnings=[],
        source="alpha_verify",
    )
    session.add(row)
    session.commit()
    return row


def seed_scorecard(
    session: Session,
    *,
    symbol: str = "BTC/USD",
    strategy_id: str = "crypto_push_pull_baseline",
    verdict: str = "paper_candidate",
) -> AlphaScorecard:
    sc = AlphaScorecard(
        symbol=symbol,
        normalized_symbol=symbol.upper().replace("/", ""),
        asset_class="crypto" if "/" in symbol else "stock",
        strategy_family="momentum_continuation",
        strategy_id=strategy_id,
        timeframe="5Min",
        current_stage=verdict,
        sample_size=18,
        backtest_count=1,
        walk_forward_count=1,
        win_rate=0.58,
        expectancy=0.006,
        profit_factor=1.32,
        max_drawdown_pct=4.0,
        cost_bps=10.0,
        spread_bps=3.0,
        slippage_bps=2.0,
        fee_bps=0.0,
        edge_after_cost_bps=50.0,
        data_freshness_status="fresh",
        bar_count=80,
        quote_freshness="fresh",
        verdict=verdict,
        promotion_reason="Verifier alpha evidence.",
        evidence_ids_json=["bt_fixture_alpha"],
        scorecard_json={"composite_score": 1.0},
    )
    session.add(sc)
    session.commit()
    return sc


def seed_recent_losses(session: Session, *, symbol: str = "BTC/USD", strategy_id: str = "crypto_push_pull_baseline") -> None:
    for idx in range(2):
        session.add(
            PaperExperimentOutcome(
                strategy_id=strategy_id,
                symbol=symbol,
                realized_pnl=-0.25 - idx * 0.1,
                fees_estimated=0.02,
                exit_reason="stop_loss",
            )
        )
    session.commit()
