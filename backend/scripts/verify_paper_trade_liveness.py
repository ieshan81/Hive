"""Verify bounded paper-mode order liveness through the official cage path.

This uses a broker test double, but only by injecting it into the existing
TrainingExecutionService -> PaperExecutionService -> ExecutionCage boundary.
No live broker path is enabled and no production DB is touched.
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


tmp_db = Path(tempfile.gettempdir()) / f"hive_paper_liveness_{os.getpid()}.db"
try:
    tmp_db.unlink()
except FileNotFoundError:
    pass

os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db.as_posix()}"
os.environ["LIVE_TRADING_ARMED"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.database import (  # noqa: E402
    AccountSnapshot,
    AlphaScorecard,
    HistoricalBar,
    OrderRecord,
    PaperExperimentConfig,
    PaperExperimentDecision,
    engine,
    init_db,
)
from app.services.config_manager import ConfigManager  # noqa: E402
from app.services.default_config import DEFAULT_CONFIG  # noqa: E402
from app.services.training_execution_service import TrainingExecutionService  # noqa: E402


SYMBOL = "BTC/USD"
PRICE = 73405.0


class FakeAlpacaAdapter:
    broker_sync_rate_limited = False

    def __init__(self, session: Session):
        self.session = session

    @property
    def configured(self) -> bool:
        return True

    def get_quote(self, _symbol: str, _asset_class: str = "crypto") -> dict:
        return {
            "symbol": SYMBOL,
            "bid": 73400.0,
            "ask": 73410.0,
            "mid": PRICE,
            "spread_pct": (73410.0 - 73400.0) / PRICE,
            "quote_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def sync_account_cached(self, *, force: bool = False) -> AccountSnapshot:
        del force
        snap = self.session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()
        if snap:
            return snap
        snap = AccountSnapshot(
            equity=200.0,
            cash=200.0,
            buying_power=200.0,
            portfolio_value=200.0,
            raw_payload={"non_marginable_buying_power": 200.0, "USD": 200.0},
        )
        self.session.add(snap)
        self.session.flush()
        return snap

    def sync_positions_cached(self, *, force: bool = False) -> list:
        del force
        return []

    def get_open_orders(self) -> list:
        return []

    def submit_marketable_limit_ioc(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        limit_price: float,
        client_order_id: str | None = None,
    ) -> dict:
        return {
            "success": True,
            "order_id": "paper-liveness-order-001",
            "status": "accepted",
            "request_payload": {
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "limit_price": limit_price,
                "client_order_id": client_order_id,
                "paper_only": True,
            },
        }

    def submit_crypto_market_notional(
        self,
        symbol: str,
        notional: float,
        side: str,
        *,
        client_order_id: str | None = None,
        time_in_force: str = "gtc",
    ) -> dict:
        return {
            "success": True,
            "order_id": "paper-liveness-order-001",
            "status": "accepted",
            "request_payload": {
                "symbol": symbol,
                "notional": notional,
                "side": side,
                "client_order_id": client_order_id,
                "time_in_force": time_in_force,
                "paper_only": True,
            },
        }

    def get_order_by_id(self, _order_id: str | None) -> None:
        return None


class FakeMemeSpikeDetector:
    def __init__(self, session: Session, config: dict):
        del session, config

    def evaluate_symbol(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "suggested_action": "observe_only",
            "tier": "MAJOR_CRYPTO",
            "reason_codes": [],
        }


ASSET_META = {
    "symbol": SYMBOL,
    "id": "BTCUSD",
    "name": "Bitcoin / USD",
    "asset_class": "crypto",
    "tradable": True,
    "status": "active",
    "min_order_size": 0.00000001,
    "min_trade_increment": 0.00000001,
    "price_increment": 0.01,
    "quote_currency": "USD",
}


def _seed_config(session: Session) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.setdefault("execution", {})
    cfg["execution"]["paper_orders_enabled"] = True
    cfg["execution"]["live_orders_enabled"] = False
    cfg["execution"]["max_orders_per_cycle"] = 0
    cfg["execution"]["max_orders_per_hour"] = 0
    cfg["execution"]["max_orders_per_day"] = 0
    cfg["execution"]["min_seconds_between_orders_per_symbol"] = 0
    cfg["execution"]["quote_max_age_seconds"] = 30
    cfg["live_trading_enabled"] = False
    cfg["paper_trading_only"] = True
    cfg.setdefault("promotion", {})["current_stage"] = "PAPER"
    cfg.setdefault("autonomous_paper_learning", {})
    cfg["autonomous_paper_learning"]["mode_enabled"] = True
    cfg["autonomous_paper_learning"]["use_capital_allocator"] = True
    cfg.setdefault("portfolio", {})
    cfg["portfolio"]["reserve_cash_pct"] = 5.0
    cfg["portfolio"]["max_concurrent_positions"] = 0
    cfg.setdefault("risk", {})
    cfg["risk"]["max_exposure_per_symbol_pct"] = 100.0
    cfg["risk"]["reconciliation_drift_halt_bps"] = 999999.0
    cfg.setdefault("cost", {})
    cfg["cost"]["taker_fee_pct"] = 0.0
    cfg["cost"]["slippage_buffer_major_pct"] = 0.0
    cfg["cost"]["edge_multiplier_paper"] = 1.0
    cfg.setdefault("push_pull", {})
    cfg["push_pull"]["min_edge_after_cost_bps"] = 10.0
    cfg.setdefault("exploration", {})
    cfg["exploration"]["enabled"] = True
    cfg["exploration"]["dynamic_formula_mode"] = True
    ConfigManager(session)._activate(cfg, changed_by="verify_paper_trade_liveness", reason="isolated liveness fixture")
    return ConfigManager(session).get_current()


def _seed_bars(session: Session) -> None:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
    for timeframe, step_minutes in (("1Min", 1), ("5Min", 5)):
        for idx in range(24):
            ts = now - timedelta(minutes=step_minutes * (24 - idx))
            base = PRICE - 90 + idx * 4.5
            session.add(
                HistoricalBar(
                    symbol=SYMBOL,
                    asset_class="crypto",
                    timeframe=timeframe,
                    timestamp=ts,
                    open=base,
                    high=base + 45,
                    low=base - 35,
                    close=base + 12,
                    volume=1000 + idx * 10,
                    source="fixture",
                    synthetic=False,
                )
            )


def _seed_learning_decision(session: Session) -> PaperExperimentDecision:
    session.add(
        AlphaScorecard(
            symbol=SYMBOL,
            normalized_symbol="BTCUSD",
            asset_class="crypto",
            strategy_family="momentum_continuation",
            strategy_id="crypto_push_pull_baseline",
            timeframe="5Min",
            current_stage="paper_candidate",
            sample_size=24,
            backtest_count=1,
            walk_forward_count=1,
            win_rate=0.58,
            expectancy=0.004,
            profit_factor=1.22,
            max_drawdown_pct=4.0,
            cost_bps=2.0,
            spread_bps=1.36,
            slippage_bps=0.0,
            fee_bps=0.0,
            edge_after_cost_bps=38.0,
            data_freshness_status="fresh",
            bar_count=48,
            quote_freshness="fresh",
            verdict="paper_candidate",
            promotion_reason="Fixture alpha evidence allows bounded paper liveness.",
            evidence_ids_json=["fixture_backtest", "fixture_walk_forward"],
            scorecard_json={"fixture": True, "composite_score": 1.0},
        )
    )
    session.add(
        PaperExperimentConfig(
            profile="aggressive_paper_learning",
            mode_enabled=True,
            config_json={
                "mode_enabled": True,
                "default_experiment_notional_usd": 12.0,
                "max_experiment_notional_per_trade_usd": 0,
                "max_open_experiment_positions": 0,
                "max_experiment_trades_per_day": 0,
                "max_experiment_trades_per_strategy_per_day": 0,
                "require_position_monitor": True,
                "use_capital_allocator": True,
                "allow_live": False,
            },
        )
    )
    decision = PaperExperimentDecision(
        strategy_id="crypto_push_pull_baseline",
        symbol=SYMBOL,
        side="buy",
        requested_notional=12.0,
        approved_notional=12.0,
        decision="approved",
        reason_code="fixture_valid_candidate",
        reason_text="Fixture paper candidate with fresh quote, exit truth, and positive edge.",
        risk_snapshot_json={
            "signal_meta": {
                "paper_exploration": True,
                "paper_exploration_probe": True,
                "push_score": 0.78,
                "trade_quality_score": 0.74,
                "edge_after_cost_bps": 180.0,
                "expected_move_pct": 1.2,
                "score_components": {"spread_bps": 1.36},
            }
        },
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)
    return decision


def main() -> None:
    init_db()
    with Session(engine) as session:
        cfg = _seed_config(session)
        session.add(
            AccountSnapshot(
                equity=200.0,
                cash=200.0,
                buying_power=200.0,
                portfolio_value=200.0,
                raw_payload={"non_marginable_buying_power": 200.0, "USD": 200.0},
            )
        )
        _seed_bars(session)
        decision = _seed_learning_decision(session)

        patches = [
            patch("app.services.training_execution_service.AlpacaAdapter", FakeAlpacaAdapter),
            patch("app.services.paper_execution_service.AlpacaAdapter", FakeAlpacaAdapter),
            patch("app.trading_cage.execution_cage.AlpacaAdapter", FakeAlpacaAdapter),
            patch("app.services.quote_freshness_service.AlpacaAdapter", FakeAlpacaAdapter),
            patch("app.services.account_pair_eligibility_service.AlpacaAdapter", FakeAlpacaAdapter),
            patch("app.services.training_execution_service.MemeVolatilitySpikeDetector", FakeMemeSpikeDetector),
            patch("app.trading_cage.execution_cage.BrokerReconciliationService.exit_only_reconciliation_status", lambda _self: {"max_drift_bps": 0.0}),
            patch("app.services.alpaca_crypto_order_validator.fetch_crypto_assets", lambda: {SYMBOL: ASSET_META}),
            patch("app.services.alpaca_crypto_order_validator.get_crypto_asset", lambda _symbol: ASSET_META),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
            result = TrainingExecutionService(session, cfg).execute_approved_decision(decision.id)
            session.commit()

        session.refresh(decision)
        order = session.exec(select(OrderRecord).where(OrderRecord.symbol == SYMBOL)).first()

    assert result["status"] == "ok", result
    assert result["submitted"] is True, result
    assert result["broker_mode"] == "paper", result
    assert result["live_trading_locked"] is True, result
    assert decision.execution_status == "paper_order_submitted", decision.execution_status
    assert order is not None and order.status == "submitted", order
    assert cfg["execution"]["paper_orders_enabled"] is True
    assert cfg["execution"]["live_orders_enabled"] is False
    assert cfg["live_trading_enabled"] is False
    assert cfg["promotion"]["current_stage"] == "PAPER"

    proof = {
        "candidate_symbol": SYMBOL,
        "alpha_candidate_evidence": "paper_candidate scorecard fixture",
        "sizing_result": {"approved_notional": decision.approved_notional, "order_qty": order.qty},
        "cage_approval": {
            "execution_status": result["execution_status"],
            "reject_reason": result["reject_reason"],
            "blocked_before_broker": result["blocked_before_broker"],
        },
        "order_submission_intent": {
            "broker_order_id": result["broker_order_id"],
            "local_order_status": order.status,
            "client_order_id": order.broker_client_order_id,
        },
        "paper_only": result["broker_mode"] == "paper",
        "live_locked": result["live_trading_locked"] is True,
    }
    print("verify_paper_trade_liveness: PASS")
    print(proof)


if __name__ == "__main__":
    main()
