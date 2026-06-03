"""Shadow promotion ladder — L0→L3 learning stages; L3 is NOT a broker paper bypass."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ShadowTrade
from app.services.engine_config import cfg_get
from app.services.nuke_epoch_service import PAPER_VALIDATION_RUN_ID, get_latest_reset_epoch
from app.services.shadow_league_constants import (
    DATA_EXECUTION_GRADE,
    DATA_NOT_BROKER_QUALITY,
    DATA_STALE,
    LEVEL_OBSERVED,
    LEVEL_PAPER_CANDIDATE,
    LEVEL_SHADOW_PROVEN,
    LEVEL_SHADOW_TRADE,
    LEVEL_LABELS,
    STATUS_CLOSED,
)
from app.services.shadow_trade_service import shadow_league_enabled


class ShadowPromotionLadderService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or {}

    def reevaluate_all(self) -> int:
        """Promote closed shadow trades on ladder rules."""
        if not shadow_league_enabled(self.config):
            return 0
        sl = self.config.get("shadow_league") or {}
        min_wins = int(sl.get("shadow_proven_min_wins", 2))
        min_closed = int(sl.get("shadow_proven_min_closed", 3))
        run_id = (get_latest_reset_epoch(self.session) or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID

        promoted = 0
        for fp in self._fingerprints_for_run(run_id):
            if self._maybe_promote_fingerprint(fp, run_id, min_wins=min_wins, min_closed=min_closed):
                promoted += 1
        if promoted:
            self.session.commit()
        return promoted

    def ladder_summary(self) -> dict[str, Any]:
        run_id = (get_latest_reset_epoch(self.session) or {}).get("validation_run_id") or PAPER_VALIDATION_RUN_ID
        rows = list(
            self.session.exec(select(ShadowTrade).where(ShadowTrade.validation_run_id == run_id)).all()
        )
        by_level: dict[str, int] = {LABEL: 0 for LABEL in LEVEL_LABELS.values()}
        for r in rows:
            lbl = LEVEL_LABELS.get(r.promotion_level, "unknown")
            by_level[lbl] = by_level.get(lbl, 0) + 1

        closest = self._closest_to_paper(rows)
        return {
            "validation_run_id": run_id,
            "total_records": len(rows),
            "by_level": by_level,
            "closest_to_paper_promotion": closest,
            "ladder_stages": [
                {"level": 0, "name": LEVEL_LABELS[LEVEL_OBSERVED], "meaning": "Setup observed, no virtual fill"},
                {"level": 1, "name": LEVEL_LABELS[LEVEL_SHADOW_TRADE], "meaning": "Virtual shadow trade open/closed"},
                {"level": 2, "name": LEVEL_LABELS[LEVEL_SHADOW_PROVEN], "meaning": "Shadow wins meet proof threshold"},
                {
                    "level": 3,
                    "name": LEVEL_LABELS[LEVEL_PAPER_CANDIDATE],
                    "meaning": "Eligible for paper review — still requires cage/alpha gates",
                },
            ],
            "direct_broker_paper_forbidden": True,
            "counts_as_broker_evidence": False,
        }

    def _fingerprints_for_run(self, run_id: str) -> set[str]:
        rows = self.session.exec(
            select(ShadowTrade.setup_fingerprint).where(ShadowTrade.validation_run_id == run_id)
        ).all()
        return {r for r in rows if r}

    def _maybe_promote_fingerprint(self, fp: str, run_id: str, *, min_wins: int, min_closed: int) -> bool:
        closed = list(
            self.session.exec(
                select(ShadowTrade).where(
                    ShadowTrade.setup_fingerprint == fp,
                    ShadowTrade.validation_run_id == run_id,
                    ShadowTrade.status == STATUS_CLOSED,
                    ShadowTrade.promotion_level >= LEVEL_SHADOW_TRADE,
                )
            ).all()
        )
        if len(closed) < min_closed:
            return False
        wins = sum(1 for c in closed if c.outcome_verdict == "win")
        if wins < min_wins:
            return False

        anchor = max(closed, key=lambda r: r.closed_at or r.created_at)
        if anchor.promotion_level >= LEVEL_SHADOW_PROVEN:
            proven_row = anchor
        else:
            anchor.promotion_level = LEVEL_SHADOW_PROVEN
            anchor.updated_at = datetime.utcnow()
            self.session.add(anchor)
            proven_row = anchor

        sl = self.config.get("shadow_league") or {}
        if proven_row.promotion_level < LEVEL_PAPER_CANDIDATE:
            stock_ok = proven_row.asset_class != "stock" or proven_row.data_quality == DATA_EXECUTION_GRADE
            if sl.get("stock_requires_execution_grade_for_paper_candidate", True) and not stock_ok:
                return True
            if proven_row.data_quality in (DATA_STALE, DATA_NOT_BROKER_QUALITY) and proven_row.asset_class == "stock":
                return True
            proven_row.promotion_level = LEVEL_PAPER_CANDIDATE
            proven_row.updated_at = datetime.utcnow()
            self.session.add(proven_row)
        return True

    def _closest_to_paper(self, rows: list[ShadowTrade]) -> dict[str, Any]:
        candidates = [r for r in rows if r.promotion_level >= LEVEL_SHADOW_TRADE]
        if not candidates:
            obs = [r for r in rows if r.promotion_level == LEVEL_OBSERVED]
            if obs:
                best = max(obs, key=lambda r: (r.evidence_json or {}).get("trade_quality_score") or 0)
                return {
                    "symbol": best.symbol,
                    "promotion_level": best.promotion_level,
                    "level_name": LEVEL_LABELS[LEVEL_OBSERVED],
                    "missing_evidence": ["shadow_trade", "shadow_proven_wins"],
                }
            return {"symbol": None, "missing_evidence": ["any_observed_setup"]}

        ranked = sorted(
            candidates,
            key=lambda r: (r.promotion_level, r.simulated_pnl_bps or 0),
            reverse=True,
        )
        best = ranked[0]
        missing: list[str] = []
        sl = self.config.get("shadow_league") or {}
        min_wins = int(sl.get("shadow_proven_min_wins", 2))
        min_closed = int(sl.get("shadow_proven_min_closed", 3))

        if best.promotion_level < LEVEL_SHADOW_PROVEN:
            missing.append(f"need_{min_closed}_closed_shadow_trades")
            missing.append(f"need_{min_wins}_shadow_wins")
        if best.promotion_level < LEVEL_PAPER_CANDIDATE:
            missing.append("shadow_proven_setup")
            if best.asset_class == "stock" and best.data_quality != DATA_EXECUTION_GRADE:
                missing.append("stock_execution_grade_data")
        if best.promotion_level == LEVEL_PAPER_CANDIDATE:
            missing.extend(["alpha_paper_candidate_verdict", "cage_preflight_pass", "operator_paper_enable"])

        return {
            "symbol": best.symbol,
            "strategy_id": best.strategy_id,
            "promotion_level": best.promotion_level,
            "level_name": LEVEL_LABELS.get(best.promotion_level, "unknown"),
            "data_quality": best.data_quality,
            "missing_evidence": missing,
            "note": "Level 3 is shadow paper-candidate only — broker paper still requires full gates.",
        }
