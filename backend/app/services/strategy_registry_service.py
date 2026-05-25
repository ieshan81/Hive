"""Living strategy registry — sync from lab, read APIs, no trading."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import (
    LessonNode,
    ParameterSetResult,
    PositionEnrichedState,
    PositionSnapshot,
    ResearchBacktestRun,
    StrategyCandidate,
    StrategyDefinition,
    StrategyRegistry,
)
from app.services.config_manager import ConfigManager
from app.services.memory_categories import RESEARCH_MEMORY_TYPES
from app.services.research_performance import evaluate_metrics
from app.services.strategy_library import STRATEGY_CATALOG, list_strategies, seed_strategy_library
from app.services.strategy_memory_validation_service import StrategyMemoryValidationService
from app.services.strategy_promotion_seed import seed_promotion_rules


def _code_hash(strategy_id: str, params: dict | None, version: str) -> str:
    blob = json.dumps({"id": strategy_id, "v": version, "p": params or {}}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class StrategyRegistryService:
    def __init__(self, session: Session):
        self.session = session
        self.config = ConfigManager(session).get_current()
        self.live_locked = not bool(
            (self.config.get("locked_safety_caps") or {}).get("live_trading_enabled", False)
            or self.config.get("live_trading_enabled", False)
        )

    def sync_from_lab(self) -> dict[str, Any]:
        seed_strategy_library(self.session)
        seed_promotion_rules(self.session)
        mem_svc = StrategyMemoryValidationService(self.session, self.config)
        created = updated = 0
        open_positions = list(
            self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()
        )
        enriched = {
            r.broker_symbol: (r.state_json or {})
            for r in self.session.exec(select(PositionEnrichedState)).all()
        }

        defs = {d.strategy_id: d for d in self.session.exec(select(StrategyDefinition)).all()}
        all_ids = sorted(set(defs.keys()) | {c["strategy_id"] for c in STRATEGY_CATALOG} | {"crypto_push_pull"})
        for sid in all_ids:
            defn = defs.get(sid)
            catalog = next((c for c in STRATEGY_CATALOG if c["strategy_id"] == sid), None)
            if not defn and not catalog and sid != "crypto_push_pull":
                continue

            stage, meta = self._infer_stage(
                sid, defn, catalog, open_positions, enriched
            )
            params = (defn.parameters_json if defn else None) or (
                (catalog or {}).get("parameters_json") or {}
            )
            if sid == "crypto_push_pull":
                name = "Crypto Push-Pull (Runtime)"
                family = "crypto_push_pull"
            else:
                name = (defn.strategy_name if defn else None) or (
                    (catalog or {}).get("strategy_name") or sid
                )
                family = (defn.strategy_family if defn else None) or (
                    (catalog or {}).get("strategy_family") or sid
                )
            reg = self.session.exec(
                select(StrategyRegistry).where(StrategyRegistry.strategy_id == sid)
            ).first()
            ch = _code_hash(sid, params, "1.0.0")
            if not reg:
                reg = StrategyRegistry(
                    strategy_id=sid,
                    name=name,
                    family=family or sid,
                    code_hash=ch,
                    asset_class=(defn.asset_class if defn else (catalog or {}).get("asset_class", "crypto")),
                    symbols=list(defn.universe) if defn else (catalog or {}).get("universe", []),
                    timeframe=(defn.timeframe if defn else (catalog or {}).get("timeframe", "1h")),
                    parameter_schema_json=(catalog or {}).get("parameter_schema_json"),
                    active_parameters_json=(catalog or {}).get("default_parameters_json") or params,
                    current_stage=stage,
                    can_trade_paper=stage in ("paper_active", "paper_candidate"),
                    can_trade_live=False,
                    live_locked=True,
                    quarantine_status=meta.get("quarantine"),
                )
                created += 1
            else:
                if reg.code_hash and reg.code_hash != ch and reg.current_stage == "rejected":
                    reg.current_stage = "research_only"
                    reg.quarantine_status = None
                reg.name = name
                reg.family = family or sid
                reg.code_hash = ch
                reg.previous_stage = reg.current_stage if reg.current_stage != stage else reg.previous_stage
                reg.current_stage = stage
                reg.can_trade_paper = stage == "paper_active"
                reg.can_trade_live = False
                reg.live_locked = True
                reg.quarantine_status = meta.get("quarantine")
                reg.latest_backtest_run_id = meta.get("latest_backtest_run_id")
                reg.latest_rejection_id = meta.get("latest_rejection_id")
                updated += 1

            bt = self.session.exec(
                select(ResearchBacktestRun)
                .where(ResearchBacktestRun.strategy_id == sid)
                .order_by(ResearchBacktestRun.created_at.desc())
            ).first()
            if bt:
                reg.latest_backtest_run_id = bt.run_id

            self.session.add(reg)
            mem_svc.link_research_memories(sid)

        self.session.flush()
        return {
            "status": "ok",
            "created": created,
            "updated": updated,
            "total": len(self.session.exec(select(StrategyRegistry)).all()),
        }

    def _infer_stage(
        self,
        sid: str,
        defn: Optional[StrategyDefinition],
        catalog: Optional[dict],
        open_positions: list,
        enriched: dict,
    ) -> tuple[str, dict]:
        meta: dict[str, Any] = {}
        cand = self.session.exec(
            select(StrategyCandidate).where(StrategyCandidate.strategy_id == sid)
        ).first()
        if cand and cand.status == "rejected":
            meta["latest_rejection_id"] = cand.id
            return "rejected", meta

        metrics = self._latest_metrics(sid)
        rej_mem = self.session.exec(
            select(LessonNode).where(
                LessonNode.strategy_name == sid,
                LessonNode.memory_type == "rejected_strategy_memory",
            )
        ).first()
        ev = evaluate_metrics(metrics, self.config)
        if sid == "crypto_push_pull":
            for p in open_positions:
                st = enriched.get(p.symbol, {})
                strat = st.get("strategy_name") or st.get("strategy_id")
                if strat and "push" in str(strat).lower():
                    meta["quarantine"] = "open_position_exists"
                    return "paper_active", meta
            if any("DOGE" in (p.symbol or "").upper() for p in open_positions):
                meta["quarantine"] = "open_doge_position"
                return "paper_active", meta

        if sid == "crypto_push_pull_momentum":
            if rej_mem or (cand and cand.status == "rejected"):
                return "rejected", meta
            if ev["reject"] and metrics.get("num_trades", 0) >= 20:
                return "rejected", meta

        if ev["reject"] and metrics.get("num_trades", 0) >= 20 and sid != "crypto_push_pull":
            return "rejected", meta

        if cand and cand.promotion_stage in ("paper_candidate", "paper_enabled"):
            return "paper_candidate", meta

        if metrics.get("num_trades", 0) >= 100 and ev.get("promote_allowed"):
            return "watchlist", meta

        if metrics.get("num_trades", 0) >= 50:
            return "research_only", meta

        return "research_only", meta

    def _latest_metrics(self, sid: str) -> dict:
        rows = list(
            self.session.exec(
                select(ParameterSetResult)
                .where(ParameterSetResult.strategy_id == sid)
                .order_by(ParameterSetResult.created_at.desc())
                .limit(5)
            ).all()
        )
        if not rows:
            return {"num_trades": 0}
        return {
            "expectancy": sum(float(r.expectancy or 0) for r in rows) / len(rows),
            "profit_factor": sum(float(r.profit_factor or 0) for r in rows) / len(rows),
            "max_drawdown_pct": max(float(r.max_drawdown_pct or 0) for r in rows),
            "num_trades": max(int(r.num_trades or 0) for r in rows),
        }

    def list_registry(self, stage: Optional[str] = None) -> list[dict]:
        q = select(StrategyRegistry)
        if stage:
            q = q.where(StrategyRegistry.current_stage == stage)
        rows = self.session.exec(q.order_by(StrategyRegistry.updated_at.desc())).all()
        return [self._serialize(r) for r in rows]

    def get(self, strategy_id: str) -> Optional[dict]:
        r = self.session.exec(
            select(StrategyRegistry).where(StrategyRegistry.strategy_id == strategy_id)
        ).first()
        return self._serialize(r) if r else None

    def tab_snapshot(self) -> dict[str, Any]:
        all_rows = self.list_registry()
        return {
            "live_locked": True,
            "live_trading_enabled": False,
            "paper_trading_only": True,
            "counts": {
                "total": len(all_rows),
                "active": sum(1 for r in all_rows if r["current_stage"] in ("paper_active", "tiny_live", "standard_live")),
                "paper_candidates": sum(1 for r in all_rows if r["current_stage"] == "paper_candidate"),
                "rejected": sum(1 for r in all_rows if r["current_stage"] == "rejected"),
                "watchlist": sum(1 for r in all_rows if r["current_stage"] == "watchlist"),
                "stale_warnings": sum(1 for r in all_rows if r.get("data_warning")),
            },
            "strategies": all_rows,
        }

    def _serialize(self, r: StrategyRegistry) -> dict:
        blockers = []
        if r.quarantine_status:
            blockers.append(r.quarantine_status)
        if r.live_locked:
            blockers.append("live_trading_locked")
        if r.current_stage == "rejected":
            blockers.append("research_rejected")
        return {
            "id": r.id,
            "strategy_id": r.strategy_id,
            "name": r.name,
            "family": r.family,
            "version": r.version,
            "code_hash": r.code_hash,
            "asset_class": r.asset_class,
            "symbols": r.symbols,
            "timeframe": r.timeframe,
            "author_type": r.author_type,
            "current_stage": r.current_stage,
            "previous_stage": r.previous_stage,
            "current_score": r.current_score,
            "confidence": r.confidence,
            "risk_tier": r.risk_tier,
            "can_trade_paper": r.can_trade_paper,
            "can_trade_live": r.can_trade_live,
            "live_locked": r.live_locked,
            "quarantine_status": r.quarantine_status,
            "memory_count": r.memory_count,
            "validated_memory_count": r.validated_memory_count,
            "pending_memory_count": r.pending_memory_count,
            "latest_backtest_run_id": r.latest_backtest_run_id,
            "blockers": blockers,
            "why_active": r.quarantine_status if r.current_stage == "paper_active" else None,
            "updated_at": r.updated_at.isoformat() + "Z" if r.updated_at else None,
        }
