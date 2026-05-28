"""Portfolio gate — Top-N selection, exposure, correlation, ranking."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.database import PortfolioDecision, PositionSnapshot
from app.services.engine_config import cfg_get, current_promotion_stage
from app.services.portfolio_correlation import correlation_penalty_for_candidate


@dataclass
class ApprovedCandidate:
    signal_id: int
    symbol: str
    side: str
    signal_type: str
    meta: dict
    strength: float
    confidence: float
    spread_pct: Optional[float]
    liquidity_score: Optional[float]
    edge_over_cost: Optional[float]
    expected_move_pct: Optional[float]
    position_qty: float
    entry_price: float
    stop_loss: float
    atr14: Optional[float]
    tier: str
    cost_evidence: dict
    sizing_evidence: dict


@dataclass
class PortfolioGateResult:
    decisions: list[PortfolioDecision] = field(default_factory=list)
    selected: list[ApprovedCandidate] = field(default_factory=list)
    deferred_count: int = 0
    blocked_count: int = 0


def _stage_portfolio_value(config: dict, key: str, default: float) -> float:
    stage = current_promotion_stage(config)
    stage_block = cfg_get(config, f"promotion.stages.{stage}.portfolio", {}) or {}
    if isinstance(stage_block, dict) and key in stage_block:
        return float(stage_block[key])
    return float(cfg_get(config, f"portfolio.{key}", default))


def _zero_or_negative_means_unlimited(value: Any) -> bool:
    try:
        return int(value) <= 0
    except (TypeError, ValueError):
        return False


def compute_ranking_score(
    config: dict,
    cand: ApprovedCandidate,
    *,
    memory_penalty: float = 0,
    cooldown_penalty: float = 0,
    correlation_penalty: float = 0,
) -> tuple[float, dict]:
    w = cfg_get(config, "ranking", {}) or {}
    meta = cand.meta or {}
    strength = cand.strength or 0
    conf = cand.confidence or 0
    eoc = cand.edge_over_cost or meta.get("edge_over_cost") or 0
    spread_q = 1.0 - min(1.0, (cand.spread_pct or 0) * 100) if cand.spread_pct else None
    liq = (cand.liquidity_score or 0) / 100.0 if cand.liquidity_score else None
    vol_pen = float(meta.get("volatility_penalty") or meta.get("volatility") or 0)

    components: dict[str, Any] = {}
    score = 0.0
    missing: list[str] = []

    def add(name: str, weight_key: str, value: Optional[float], normalize: bool = False):
        nonlocal score
        wt = float(w.get(weight_key, 0))
        if value is None:
            missing.append(name)
            components[name] = {"weight": wt, "value": None, "contribution": 0}
            return
        v = float(value)
        if normalize:
            v = max(0.0, min(1.0, v))
        contrib = wt * v
        score += contrib
        components[name] = {"weight": wt, "value": v, "contribution": contrib}

    add("signal_strength", "w_signal_strength", strength, normalize=True)
    add("confidence", "w_confidence", conf, normalize=True)
    add("edge_over_cost", "w_edge_over_cost", min(3.0, eoc) / 3.0 if eoc else None, normalize=True)
    add("spread_quality", "w_spread_quality", spread_q)
    add("liquidity", "w_liquidity", liq)
    if vol_pen:
        score -= float(w.get("w_volatility_anomaly", 0)) * vol_pen
    score -= float(w.get("w_memory_penalty", 0)) * memory_penalty
    score -= float(w.get("w_correlation_penalty", 0)) * correlation_penalty
    if cooldown_penalty:
        score -= cooldown_penalty * 0.1
    if memory_penalty:
        score -= memory_penalty
        components["memory_penalty"] = memory_penalty

    for h in ("momentum_1h", "momentum_3h", "momentum_6h", "momentum_12h"):
        if h in meta:
            components[h] = meta[h]

    components["missing"] = missing
    components["raw_score"] = score
    return score, components


class PortfolioGate:
    def __init__(self, session: Session, config: dict, alpaca=None):
        self.session = session
        self.config = config
        self.alpaca = alpaca

    def run(
        self,
        cycle_run_id: str,
        candidates: list[ApprovedCandidate],
        *,
        equity: float,
        cash: float,
        buying_power: float,
        positions: list[PositionSnapshot],
        open_order_symbols: set[str],
        promotion_stage: str,
    ) -> PortfolioGateResult:
        result = PortfolioGateResult()
        if not candidates:
            return result

        top_n = int(_stage_portfolio_value(self.config, "execute_top_n_signals", 1))
        raw_max_concurrent = _stage_portfolio_value(self.config, "max_concurrent_positions", 2)
        max_concurrent_unlimited = _zero_or_negative_means_unlimited(raw_max_concurrent)
        max_concurrent = 0 if max_concurrent_unlimited else int(raw_max_concurrent)
        max_exposure_pct = _stage_portfolio_value(self.config, "max_total_exposure_pct", 40.0) / 100.0
        reserve_pct = _stage_portfolio_value(self.config, "reserve_cash_pct", 60.0) / 100.0
        score_min = float(cfg_get(self.config, "portfolio.signal_score_min", 0.35))
        corr_threshold = float(cfg_get(self.config, "portfolio.correlation_block_threshold", 0.70))
        lookback_h = int(cfg_get(self.config, "portfolio.correlation_lookback_hours", 720))

        open_positions = [p for p in positions if (p.qty or 0) > 0]
        current_exposure = sum(abs(p.market_value or 0) for p in open_positions)
        exposure_ratio = current_exposure / equity if equity > 0 else 0

        ranked: list[tuple[float, ApprovedCandidate, dict]] = []
        memory_pen_fn = None
        try:
            from app.services.config_manager import ConfigManager
            from app.services.lesson_memory_service import LessonMemoryService

            mem_cfg = ConfigManager(self.session).get_current()
            if mem_cfg.get("memory", {}).get("enabled", True):
                lms = LessonMemoryService(self.session, mem_cfg)
                memory_pen_fn = lms.symbol_memory_penalty
        except Exception:
            pass

        for cand in candidates:
            mem_pen = memory_pen_fn(cand.symbol) if memory_pen_fn else 0.0
            corr_pen, corr_ev = correlation_penalty_for_candidate(
                self.alpaca,
                cand.symbol,
                open_positions,
                threshold=corr_threshold,
                lookback_hours=lookback_h,
            )
            score, comp = compute_ranking_score(
                self.config, cand, correlation_penalty=corr_pen, memory_penalty=mem_pen
            )
            ranked.append((score, cand, {**comp, "correlation": corr_ev}))

        ranked.sort(key=lambda x: x[0], reverse=True)

        selected_count = 0
        for rank_idx, (score, cand, comp) in enumerate(ranked, start=1):
            status = "portfolio_approved"
            reason = None
            human = None
            selected = False

            if score < score_min:
                status = "portfolio_blocked"
                reason = "SIGNAL_SCORE_BELOW_PORTFOLIO_MIN"
                human = f"Ranking score {score:.3f} below minimum {score_min}"
                result.blocked_count += 1
            elif cand.symbol in open_order_symbols:
                status = "portfolio_blocked"
                reason = "OPEN_ORDER_ALREADY_EXISTS"
                human = "Open order already exists for symbol"
                result.blocked_count += 1
            elif any(p.symbol == cand.symbol for p in open_positions) and cand.signal_type == "entry":
                status = "portfolio_blocked"
                reason = "DUPLICATE_SYMBOL_POSITION"
                human = "Already holding symbol"
                result.blocked_count += 1
            elif (
                not max_concurrent_unlimited
                and len(open_positions) >= max_concurrent
                and cand.signal_type == "entry"
            ):
                status = "portfolio_deferred"
                reason = "MAX_CONCURRENT_POSITIONS"
                human = f"Max concurrent positions ({max_concurrent}) reached"
                result.deferred_count += 1
            elif exposure_ratio >= max_exposure_pct and cand.signal_type == "entry":
                status = "portfolio_deferred"
                reason = "MAX_TOTAL_EXPOSURE"
                human = f"Total exposure {exposure_ratio:.1%} at cap"
                result.deferred_count += 1
            elif cash < equity * reserve_pct and cand.signal_type == "entry":
                status = "portfolio_deferred"
                reason = "RESERVE_CASH_REQUIRED"
                human = "Reserve cash requirement not met"
                result.deferred_count += 1
            elif selected_count >= top_n and cand.signal_type == "entry":
                status = "portfolio_deferred"
                reason = "TOP_N_LIMIT"
                human = f"Deferred — Top-{top_n} limit (rank {rank_idx})"
                result.deferred_count += 1
            else:
                corr_ev = comp.get("correlation", {})
                if corr_ev.get("correlation_status") == "blocked":
                    status = "portfolio_deferred"
                    reason = "CORRELATION_TOO_HIGH"
                    human = corr_ev.get("human_reason", "Correlation too high with open position")
                    result.deferred_count += 1
                elif corr_ev.get("correlation_status") == "insufficient_data":
                    comp["correlation_note"] = "insufficient_data — conservative pass"

            if status == "portfolio_approved" and cand.signal_type == "entry":
                if selected_count < top_n:
                    selected = True
                    selected_count += 1
                    result.selected.append(cand)
                else:
                    status = "portfolio_deferred"
                    reason = "TOP_N_LIMIT"
                    human = f"Deferred — Top-{top_n} limit"
                    result.deferred_count += 1

            if cand.signal_type == "exit" and status == "portfolio_approved":
                selected = True
                result.selected.append(cand)

            evidence = {
                "ranking_components": comp,
                "promotion_stage": promotion_stage,
                "top_n": top_n,
                "max_concurrent": None if max_concurrent_unlimited else max_concurrent,
                "max_concurrent_policy": "unlimited" if max_concurrent_unlimited else "capped",
                "exposure_ratio": exposure_ratio,
            }
            dec = PortfolioDecision(
                cycle_run_id=cycle_run_id,
                signal_id=cand.signal_id,
                symbol=cand.symbol,
                side=cand.side,
                signal_type=cand.signal_type,
                portfolio_status=status,
                portfolio_reason_code=reason,
                human_reason=human,
                ranking_score=score,
                portfolio_rank=rank_idx,
                selected_for_execution=selected,
                evidence_json=evidence,
            )
            self.session.add(dec)
            result.decisions.append(dec)

        return result
