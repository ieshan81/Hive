"""Shadow trade creation — learning-only virtual trades; never touches the broker."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ShadowTrade
from app.services.engine_config import cfg_get
from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch
from app.services.shadow_league_constants import (
    DATA_DELAYED,
    DATA_EXECUTION_GRADE,
    DATA_NOT_BROKER_QUALITY,
    DATA_STALE,
    LEVEL_OBSERVED,
    LEVEL_SHADOW_TRADE,
    STATUS_OBSERVED,
    STATUS_OPEN,
)


def shadow_league_enabled(config: Optional[dict]) -> bool:
    cfg = config or {}
    sl = cfg.get("shadow_league") or {}
    if sl.get("enabled") is False:
        return False
    return bool(cfg_get(cfg, "shadow_league.enabled", True))


def _validation_run_id(session: Session) -> str:
    epoch = get_latest_reset_epoch(session)
    return (epoch or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID


def setup_fingerprint(symbol: str, strategy_id: Optional[str], row: dict[str, Any]) -> str:
    payload = {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "side": "buy",
        "push": round(float(row.get("push_score") or 0), 4),
        "quality": round(float(row.get("trade_quality_score") or 0), 4),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def classify_shadow_data_quality(row: dict[str, Any], config: Optional[dict]) -> tuple[str, str]:
    """Classify bar/quote/lane quality for shadow records (stocks may be non-broker-grade)."""
    asset = str(row.get("asset_class") or ("crypto" if "/" in str(row.get("symbol") or "") else "stock")).lower()
    bar_f = str(row.get("bar_freshness") or "unknown")
    quote_f = str(row.get("quote_freshness") or "unknown")
    reason = str(row.get("no_trade_reason") or "")

    if asset == "stock":
        from app.services.stock_lane_policy import stock_lane_entry_decision, stock_lane_mode

        mode = stock_lane_mode(config)
        lane = stock_lane_entry_decision(
            mode=mode,
            freshness_status=bar_f if bar_f in ("fresh", "stale", "missing") else "stale",
            market_open=bool(row.get("market_open", True)),
            feed=row.get("stock_data_feed"),
            subscription=row.get("stock_subscription"),
        )
        if not lane.get("stock_entries_allowed"):
            note = lane.get("reason") or "Stock lane blocks paper entries"
            if bar_f != "fresh" or quote_f != "fresh":
                return DATA_STALE, f"{note}; bars/quotes not execution-grade."
            return DATA_NOT_BROKER_QUALITY, note

    if bar_f == "stale" or quote_f == "stale" or reason.upper() in ("STALE_BAR", "DATA_STALE", "STALE_QUOTE"):
        return DATA_STALE, "Stale bars or quotes — shadow-only, not broker-quality."
    if bar_f != "fresh" or quote_f != "fresh":
        return DATA_DELAYED, "Delayed or partial data — shadow learning allowed."
    return DATA_EXECUTION_GRADE, "Execution-grade data for shadow simulation."


def _reference_price(row: dict[str, Any]) -> Optional[float]:
    for key in ("mid_price", "last_price", "close", "reference_price"):
        v = row.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    levels = row.get("dynamic_exit_levels") or {}
    return levels.get("entry_reference") or levels.get("invalidation_price")


class ShadowTradeService:
    """Create shadow league records from push-pull setups without broker submission."""

    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def consider_setup(
        self,
        row: dict[str, Any],
        *,
        strategy_id: Optional[str] = None,
        paper_blocked_reason: Optional[str] = None,
        paper_submitted: bool = False,
        cycle_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record observed setup (L0) and optionally open shadow trade (L1) when paper is blocked."""
        if not shadow_league_enabled(self.config):
            return {"status": "disabled"}

        sym = str(row.get("symbol") or "")
        if not sym:
            return {"status": "skipped", "reason": "no_symbol"}

        sl = self.config.get("shadow_league") or {}
        min_obs = float(sl.get("min_quality_for_observation", cfg_get(self.config, "shadow_league.min_quality_for_observation", 0.35)))
        min_trade = float(sl.get("min_quality_for_shadow_trade", cfg_get(self.config, "shadow_league.min_quality_for_shadow_trade", 0.42)))
        quality = float(row.get("trade_quality_score") or 0)
        asset = str(row.get("asset_class") or ("crypto" if "/" in sym else "stock")).lower()

        if asset == "stock" and not bool(sl.get("allow_stock", cfg_get(self.config, "shadow_league.allow_stock", True))):
            return {"status": "skipped", "reason": "stock_shadow_disabled"}
        if asset == "crypto" and not bool(sl.get("allow_crypto", cfg_get(self.config, "shadow_league.allow_crypto", True))):
            return {"status": "skipped", "reason": "crypto_shadow_disabled"}

        fp = setup_fingerprint(sym, strategy_id, row)
        data_quality, dq_note = classify_shadow_data_quality(row, self.config)
        run_id = _validation_run_id(self.session)
        out: dict[str, Any] = {"symbol": sym, "fingerprint": fp, "data_quality": data_quality}

        if quality >= min_obs:
            obs = self._upsert_level(
                sym=sym,
                strategy_id=strategy_id,
                fp=fp,
                level=LEVEL_OBSERVED,
                status=STATUS_OBSERVED,
                row=row,
                data_quality=data_quality,
                dq_note=dq_note,
                paper_blocked_reason=paper_blocked_reason,
                paper_submitted=paper_submitted,
                run_id=run_id,
                cycle_run_id=cycle_run_id,
            )
            out["observation"] = obs

        paper_blocked = bool(paper_blocked_reason) or not bool(row.get("entry_allowed"))
        if paper_submitted:
            out["shadow_trade"] = {"status": "skipped", "reason": "paper_order_submitted_this_tick"}
            return out

        if quality < min_trade:
            out["shadow_trade"] = {"status": "skipped", "reason": "quality_below_shadow_floor"}
            return out

        if not paper_blocked and bool(row.get("entry_allowed")):
            out["shadow_trade"] = {"status": "skipped", "reason": "paper_path_open_not_shadow_substitute"}
            return out

        if self._open_count(run_id) >= int(sl.get("max_open_shadow_trades", 20)):
            out["shadow_trade"] = {"status": "skipped", "reason": "max_open_shadow_trades"}
            return out

        if self._has_open_fingerprint(fp, run_id):
            out["shadow_trade"] = {"status": "skipped", "reason": "duplicate_open_shadow"}
            return out

        trade = self._upsert_level(
            sym=sym,
            strategy_id=strategy_id,
            fp=fp,
            level=LEVEL_SHADOW_TRADE,
            status=STATUS_OPEN,
            row=row,
            data_quality=data_quality,
            dq_note=dq_note,
            paper_blocked_reason=paper_blocked_reason or row.get("no_trade_reason"),
            paper_submitted=False,
            run_id=run_id,
            cycle_run_id=cycle_run_id,
        )
        out["shadow_trade"] = trade
        return out

    def _open_count(self, run_id: str) -> int:
        rows = self.session.exec(
            select(ShadowTrade).where(
                ShadowTrade.validation_run_id == run_id,
                ShadowTrade.status == STATUS_OPEN,
                ShadowTrade.promotion_level >= LEVEL_SHADOW_TRADE,
            )
        ).all()
        return len(rows)

    def _has_open_fingerprint(self, fp: str, run_id: str) -> bool:
        return bool(
            self.session.exec(
                select(ShadowTrade).where(
                    ShadowTrade.setup_fingerprint == fp,
                    ShadowTrade.validation_run_id == run_id,
                    ShadowTrade.status == STATUS_OPEN,
                )
            ).first()
        )

    def _upsert_level(
        self,
        *,
        sym: str,
        strategy_id: Optional[str],
        fp: str,
        level: int,
        status: str,
        row: dict[str, Any],
        data_quality: str,
        dq_note: str,
        paper_blocked_reason: Optional[str],
        paper_submitted: bool,
        run_id: str,
        cycle_run_id: Optional[str],
    ) -> dict[str, Any]:
        existing = self.session.exec(
            select(ShadowTrade).where(
                ShadowTrade.setup_fingerprint == fp,
                ShadowTrade.validation_run_id == run_id,
                ShadowTrade.promotion_level == level,
                ShadowTrade.status == status,
            )
        ).first()
        if existing and status == STATUS_OBSERVED:
            return {"shadow_trade_id": existing.shadow_trade_id, "status": "exists"}

        now = datetime.utcnow()
        entry_px = _reference_price(row)
        evidence = {
            "trade_quality_score": row.get("trade_quality_score"),
            "push_score": row.get("push_score"),
            "edge_after_cost_bps": row.get("edge_after_cost_bps"),
            "gate_results": row.get("gate_results"),
            "dynamic_exit_levels": row.get("dynamic_exit_levels"),
            "no_trade_reason": row.get("no_trade_reason"),
            "entry_allowed": row.get("entry_allowed"),
            "paper_submitted": paper_submitted,
        }

        if existing and status == STATUS_OPEN:
            existing.updated_at = now
            existing.evidence_json = evidence
            existing.paper_blocked_reason = paper_blocked_reason
            self.session.add(existing)
            self.session.commit()
            return {"shadow_trade_id": existing.shadow_trade_id, "status": "updated"}

        st = ShadowTrade(
            shadow_trade_id=str(uuid.uuid4()),
            validation_run_id=run_id,
            symbol=sym,
            asset_class=str(row.get("asset_class") or ("crypto" if "/" in sym else "stock")).lower(),
            strategy_id=strategy_id,
            side="buy",
            promotion_level=level,
            status=status,
            data_quality=data_quality,
            data_quality_note=dq_note,
            entry_reference_price=entry_px,
            paper_blocked_reason=paper_blocked_reason,
            paper_would_be_allowed=bool(row.get("entry_allowed")),
            counts_as_broker_evidence=False,
            setup_fingerprint=fp,
            evidence_json=evidence,
            outcome_json={"verdict": "pending"},
            outcome_verdict="pending",
            cycle_run_id=cycle_run_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(st)
        self.session.commit()
        self.session.refresh(st)
        return {
            "shadow_trade_id": st.shadow_trade_id,
            "promotion_level": st.promotion_level,
            "status": st.status,
            "data_quality": st.data_quality,
        }
