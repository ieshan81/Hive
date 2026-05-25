"""Broker-truth reconciliation — DOGE flat vs historical buy, ghost detection, exit rejects."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord, PositionSnapshot
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.config_manager import ConfigManager
from app.services.lesson_memory_service import LessonMemoryService
from app.services.broker_safety import live_lock_status
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.position_hold_time_service import audit_all_open_positions, build_position_truth
from app.services.symbol_normalize import display_symbol, symbol_variants


CLASSIFICATIONS = (
    "ACTIVE_BROKER_POSITION",
    "BROKER_AVAILABILITY_CONFLICT",
    "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY",
    "BROKER_ACTIVITY_MISMATCH",
    "LOCAL_STALE_POSITION",
    "NO_HISTORICAL_ACTIVITY",
)


def _sym_keys(symbol: str) -> set[str]:
    keys = set()
    for v in symbol_variants(symbol):
        keys.add(v.upper().replace("/", ""))
        keys.add(normalize_crypto_symbol(v).upper().replace("/", ""))
    return keys


class BrokerReconciliationService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.lessons = LessonMemoryService(session, self.config)
        self.alpaca = AlpacaAdapter(session)

    def sync_broker_snapshots(self) -> list[PositionSnapshot]:
        if self.alpaca.configured:
            self.alpaca.sync_account()
            return self.alpaca.sync_positions() or []
        return list(self.session.exec(select(PositionSnapshot)).all())

    def broker_rejects(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.session.exec(
            select(ExecutionLog)
            .where(
                ExecutionLog.status.in_(
                    ("preflight_blocked", "paper_order_rejected", "paper_order_cancelled")
                )
            )
            .order_by(ExecutionLog.id.desc())
            .limit(limit)
        ).all()
        out = []
        for r in rows:
            gf = r.gates_failed_json or {}
            broker_msg = gf.get("broker") if isinstance(gf, dict) else None
            out.append(
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "side": r.side,
                    "status": r.status,
                    "reject_reason": r.reject_reason,
                    "broker_order_id": r.broker_order_id,
                    "cycle_run_id": r.cycle_run_id,
                    "preflight_stage": gf.get("preflight_stage"),
                    "broker_message": broker_msg,
                    "submitted_at": r.submitted_at.isoformat() + "Z" if r.submitted_at else None,
                }
            )
        return out

    def ghost_position_candidates(self) -> list[dict[str, Any]]:
        synced = self.sync_broker_snapshots()
        broker_keys = {
            normalize_crypto_symbol(p.symbol).upper().replace("/", "")
            for p in synced
            if float(getattr(p, "qty", 0) or 0) > 0
        }
        ghosts = []
        for row in self.session.exec(select(PositionSnapshot)).all():
            local_q = float(row.qty or 0)
            if local_q <= 0:
                continue
            key = normalize_crypto_symbol(row.symbol).upper().replace("/", "")
            if key not in broker_keys:
                ghosts.append(
                    {
                        "symbol": row.symbol,
                        "local_qty": local_q,
                        "broker_qty": 0,
                        "classification": "LOCAL_STALE_POSITION",
                        "synced_at": row.synced_at.isoformat() + "Z" if row.synced_at else None,
                    }
                )
        local_buy_no_broker = self._local_buy_broker_flat_candidates()
        for c in local_buy_no_broker:
            if not any(g["symbol"] == c["symbol"] for g in ghosts):
                ghosts.append(c)
        return ghosts

    def _local_buy_broker_flat_candidates(self) -> list[dict[str, Any]]:
        """Historical filled buy in DB but broker reports no open position."""
        out = []
        for order in self.session.exec(
            select(OrderRecord).where(OrderRecord.side == "buy", OrderRecord.status == "filled")
        ).all():
            sym = display_symbol(order.symbol)
            keys = _sym_keys(sym)
            broker_qty = sum(
                float(p.qty)
                for p in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all()
                if normalize_crypto_symbol(p.symbol).upper().replace("/", "") in keys
            )
            if broker_qty <= 0:
                sell_accepted = self._accepted_sell_exists(sym)
                out.append(
                    {
                        "symbol": sym,
                        "local_qty": 0,
                        "broker_qty": 0,
                        "historical_buy_order_id": order.id,
                        "historical_broker_order_id": order.alpaca_order_id,
                        "classification": "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY"
                        if not sell_accepted
                        else "BROKER_ACTIVITY_MISMATCH",
                        "filled_at": order.filled_at.isoformat() + "Z" if order.filled_at else None,
                    }
                )
        return out

    def _accepted_sell_exists(self, symbol: str) -> bool:
        """True only if broker accepted/filled a sell — rejects do not count."""
        keys = _sym_keys(symbol)
        for log in self.session.exec(
            select(ExecutionLog).where(ExecutionLog.side == "sell")
        ).all():
            if normalize_crypto_symbol(log.symbol).upper().replace("/", "") not in keys:
                continue
            if log.status in (
                "paper_order_submitted",
                "paper_order_filled",
                "paper_order_partially_filled",
            ):
                return True
        for order in self.session.exec(select(OrderRecord).where(OrderRecord.side == "sell")).all():
            if normalize_crypto_symbol(order.symbol).upper().replace("/", "") in keys:
                if order.status in ("filled", "submitted") and order.alpaca_order_id:
                    return True
        return False

    def classify_symbol(self, symbol: str = "DOGE/USD") -> dict[str, Any]:
        self.sync_broker_snapshots()
        keys = _sym_keys(symbol)
        display = display_symbol(symbol)

        synced = self.sync_broker_snapshots()
        broker_pos = None
        broker_qty = 0.0
        local_db_qty = 0.0
        available_qty: Optional[float] = None
        for p in synced:
            if normalize_crypto_symbol(p.symbol).upper().replace("/", "") in keys:
                broker_pos = p
                broker_qty = float(p.qty or 0)
                break
        for p in self.session.exec(select(PositionSnapshot)).all():
            if normalize_crypto_symbol(p.symbol).upper().replace("/", "") in keys:
                local_db_qty = float(p.qty or 0)
                if broker_pos is None and local_db_qty > 0:
                    broker_pos = p
                break

        local_qty = local_db_qty
        historical_buy = None
        for o in self.session.exec(select(OrderRecord).where(OrderRecord.side == "buy")).all():
            if normalize_crypto_symbol(o.symbol).upper().replace("/", "") in keys and o.status == "filled":
                historical_buy = o
                break

        last_exit_reject = None
        for log in self.session.exec(
            select(ExecutionLog)
            .where(ExecutionLog.side == "sell")
            .order_by(ExecutionLog.id.desc())
        ).all():
            if normalize_crypto_symbol(log.symbol).upper().replace("/", "") in keys:
                last_exit_reject = log
                break

        if last_exit_reject and last_exit_reject.gates_failed_json:
            broker_msg = (last_exit_reject.gates_failed_json or {}).get("broker", "")
            if "available" in str(broker_msg).lower():
                try:
                    parsed = json.loads(broker_msg) if broker_msg.startswith("{") else {}
                    available_qty = float(parsed.get("available", 0))
                except Exception:
                    available_qty = 0.0

        classification = "NO_HISTORICAL_ACTIVITY"
        reconciliation_state = "no_position"
        entries_blocked_reason = None

        if broker_qty > 0:
            if available_qty is not None and available_qty <= 0 and broker_qty > 0:
                classification = "BROKER_AVAILABILITY_CONFLICT"
                reconciliation_state = "broker_availability_conflict"
                entries_blocked_reason = "doge_sellable_qty_zero_broker_conflict"
            else:
                classification = "ACTIVE_BROKER_POSITION"
                reconciliation_state = "active_broker_position"
        elif historical_buy and broker_qty <= 0 and not self._accepted_sell_exists(display):
            classification = "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY"
            reconciliation_state = "broker_flat_historical_order_only"
        elif historical_buy and broker_qty <= 0:
            classification = "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY"
            reconciliation_state = "broker_flat_historical_order_only"
        elif local_db_qty > 0 and broker_qty <= 0:
            classification = "LOCAL_STALE_POSITION"
            reconciliation_state = "local_ghost_candidate"
            entries_blocked_reason = "local_stale_position_ghost"
        elif historical_buy:
            classification = "BROKER_ACTIVITY_MISMATCH"
            reconciliation_state = "broker_flat_historical_order_only"

        return {
            "symbol": display,
            "classification": classification,
            "reconciliation_state": reconciliation_state,
            "broker_position_open": broker_qty > 0,
            "broker_qty": broker_qty,
            "available_qty": available_qty,
            "local_qty": local_qty,
            "historical_buy_exists": historical_buy is not None,
            "historical_buy_order_id": historical_buy.id if historical_buy else None,
            "historical_broker_order_id": historical_buy.alpaca_order_id if historical_buy else None,
            "accepted_sell_exists": self._accepted_sell_exists(display),
            "last_exit_reject_reason": last_exit_reject.reject_reason if last_exit_reject else None,
            "last_exit_preflight_stage": (last_exit_reject.gates_failed_json or {}).get("preflight_stage")
            if last_exit_reject
            else None,
            "last_exit_broker_message": (last_exit_reject.gates_failed_json or {}).get("broker")
            if last_exit_reject
            else None,
            "entries_blocked_reason": entries_blocked_reason,
            "do_not_retry_exit_until_explained": classification == "BROKER_AVAILABILITY_CONFLICT",
        }

    def doge_audit(self) -> dict[str, Any]:
        return self.classify_symbol("DOGE/USD")

    def broker_position_availability_audit(self) -> dict[str, Any]:
        self.sync_broker_snapshots()
        audits = []
        for pos in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all():
            c = self.classify_symbol(pos.symbol)
            audits.append(c)
        flat_historical = self._local_buy_broker_flat_candidates()
        return {
            "status": "ok",
            "audited_at": datetime.utcnow().isoformat() + "Z",
            "open_broker_positions": audits,
            "flat_with_historical_buy": flat_historical,
            "ghost_candidates": self.ghost_position_candidates(),
        }

    def exit_only_reconciliation_status(self) -> dict[str, Any]:
        from app.services.fast_training_exit_only_service import FastTrainingExitOnlyService

        doge = self.doge_audit()
        eo_svc = FastTrainingExitOnlyService(self.session, self.config)
        reviews = OpenPositionReviewService(self.session, self.config).review_all()
        eo = {
            "status": "ok",
            "exit_only_enabled": bool(eo_svc.ft.get("exit_only_enabled", False)),
            "open_positions": len(reviews.get("reviews", [])),
            "entries_allowed": False,
            **live_lock_status(self.config),
        }
        ghosts = self.ghost_position_candidates()
        has_conflict = bool(ghosts) or doge.get("classification") in (
            "BROKER_AVAILABILITY_CONFLICT",
            "LOCAL_STALE_POSITION",
            "BROKER_ACTIVITY_MISMATCH",
        )
        entries_allowed = eo.get("entries_allowed", False) and not has_conflict
        blockers = []
        if has_conflict:
            blockers.append(f"reconciliation:{doge.get('classification')}")
        if doge.get("reconciliation_state") == "broker_flat_historical_order_only":
            blockers.append("broker_flat_no_open_position")
        return {
            "status": "ok",
            "doge": doge,
            "exit_only": eo,
            "entries_allowed": entries_allowed,
            "entries_blocked_reason": blockers or ["exit_only_disabled_or_training_off"],
            "open_positions_broker": eo.get("open_positions", 0),
            "reconciliation_resolved": not has_conflict,
        }

    def ensure_reconciliation_memories(self, *, actor: str = "reconciliation") -> dict[str, Any]:
        """Create audit memories once — never fake fills or delete evidence."""
        created = []
        doge = self.doge_audit()
        cls = doge.get("classification")

        if cls == "BROKER_FLAT_WITH_HISTORICAL_BUY_ONLY":
            pk = f"broker_recon|flat|DOGE|{datetime.utcnow().date()}"
            if not self._memory_exists(pk):
                self.lessons.upsert_lesson(
                    memory_type="broker_reconciliation_memory",
                    title="DOGE broker-flat with historical buy only",
                    summary=(
                        "DOGE historical buy exists, but broker currently reports no open position "
                        "and no sell order was accepted."
                    ),
                    detailed_lesson=json.dumps(doge),
                    symbol="DOGE/USD",
                    source="broker_reconciliation",
                    pattern_key=pk,
                )
                created.append("broker_reconciliation_memory")

        if cls == "BROKER_AVAILABILITY_CONFLICT":
            pk = f"broker_recon|avail|DOGE|{datetime.utcnow().date()}"
            if not self._memory_exists(pk):
                self.lessons.upsert_lesson(
                    memory_type="broker_reconciliation_memory",
                    title="DOGE broker availability conflict",
                    summary=(
                        "Broker shows position qty but available sell qty was 0 on exit attempt; "
                        "do not retry exit until explained."
                    ),
                    detailed_lesson=json.dumps(doge),
                    symbol="DOGE/USD",
                    source="broker_reconciliation",
                    pattern_key=pk,
                )
                created.append("broker_availability_conflict_memory")

        for g in self.ghost_position_candidates():
            sym = g.get("symbol", "?")
            pk = f"ghost|{sym}|{datetime.utcnow().date()}"
            if not self._memory_exists(pk):
                self.lessons.upsert_lesson(
                    memory_type="ghost_position_memory",
                    title=f"Ghost position candidate: {sym}",
                    summary="Local DB suggests open position but broker truth is flat or mismatched.",
                    detailed_lesson=json.dumps(g),
                    symbol=sym,
                    source="broker_reconciliation",
                    pattern_key=pk,
                )
                created.append("ghost_position_memory")

        for rej in self.broker_rejects(limit=5):
            if rej.get("reject_reason") not in ("BROKER_REJECTED", "BROKER_REJECTED_MIN_NOTIONAL"):
                continue
            pk = f"broker_reject|{rej.get('id')}"
            if not self._memory_exists(pk):
                self.lessons.upsert_lesson(
                    memory_type="broker_reject_memory",
                    title=f"Broker reject: {rej.get('symbol')} {rej.get('side')}",
                    summary=str(rej.get("broker_message") or rej.get("reject_reason"))[:200],
                    detailed_lesson=json.dumps(rej),
                    symbol=rej.get("symbol"),
                    source="broker_reconciliation",
                    pattern_key=pk,
                )
                created.append("broker_reject_memory")

        self.session.flush()
        return {"status": "ok", "created": created, "doge_classification": cls, "actor": actor}

    def _memory_exists(self, pattern_key: str) -> bool:
        from app.database import LessonNode

        return (
            self.session.exec(select(LessonNode).where(LessonNode.pattern_key == pattern_key)).first()
            is not None
        )

    def training_entry_blockers(self) -> list[str]:
        doge = self.doge_audit()
        blockers = []
        if doge.get("classification") == "BROKER_AVAILABILITY_CONFLICT":
            blockers.append("reconciliation:doge_availability_conflict")
        if doge.get("classification") == "LOCAL_STALE_POSITION":
            blockers.append("reconciliation:local_ghost_position")
        if doge.get("classification") == "BROKER_ACTIVITY_MISMATCH":
            blockers.append("reconciliation:broker_activity_mismatch")
        if self.ghost_position_candidates():
            blockers.append("reconciliation:ghost_position_candidates")
        if doge.get("broker_position_open"):
            blockers.append("open_position_blocks_duplicate_entry")
        return blockers

    def build_diagnostic_exports(self) -> dict[str, Any]:
        doge = self.doge_audit()
        return {
            "broker_position_availability_audit.json": self.broker_position_availability_audit(),
            "doge_broker_availability_audit.json": doge,
            "ghost_position_candidates.json": self.ghost_position_candidates(),
            "broker_rejects.json": self.broker_rejects(40),
            "exit_only_reconciliation_status.json": self.exit_only_reconciliation_status(),
            "true_hold_time_audit.json": audit_all_open_positions(self.session),
            "open_position_reviews.json": OpenPositionReviewService(self.session, self.config).review_all(),
        }
