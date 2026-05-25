"""Hive Brain node detail — drawer contract with broker source proof."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.database import LessonNode
from app.services.config_manager import ConfigManager
from app.services.lesson_memory_service import LessonMemoryService
from app.services.broker_reconciliation_service import BrokerReconciliationService
from app.services.open_position_review_service import OpenPositionReviewService
from app.services.position_hold_time_service import build_position_truth


class HiveBrainNodeService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.lessons = LessonMemoryService(session, self.config)

    def get_node(self, node_id: str) -> dict[str, Any]:
        if node_id.startswith("position-"):
            raw = node_id.replace("position-", "")
            from app.services.symbol_normalize import display_symbol

            sym = display_symbol(raw)
            recon = BrokerReconciliationService(self.session, self.config)
            doge_audit = recon.classify_symbol(sym) if "DOGE" in sym.upper() else recon.classify_symbol(sym)
            truth = build_position_truth(self.session, sym)
            review = OpenPositionReviewService(self.session, self.config).review_position(sym)
            if review.get("status") == "no_position":
                review = {**doge_audit, "status": "no_position", "action": None, "stale": False}
            return self._position_drawer(node_id, truth, review, doge_audit)

        if node_id.startswith("lesson-"):
            lid = int(node_id.replace("lesson-", ""))
            row = self.session.get(LessonNode, lid)
            if not row:
                return {"status": "error", "message": "lesson not found"}
            detail = self.lessons._lesson_detail(row)
            return self._lesson_drawer(detail)

        if node_id.startswith("strategy-"):
            sid = node_id.replace("strategy-", "")
            from sqlmodel import select
            from app.database import StrategyRegistry

            reg = self.session.exec(
                select(StrategyRegistry).where(StrategyRegistry.strategy_id == sid)
            ).first()
            if not reg:
                return {"status": "error", "message": "strategy not found"}
            return {
                "status": "ok",
                "node": {
                    "id": node_id,
                    "title": reg.name,
                    "type": "strategy",
                    "shape": "diamond",
                    "summary": f"Strategy {reg.strategy_id} at stage {reg.current_stage}",
                    "sections": {
                        "summary": {
                            "stage": reg.current_stage,
                            "why_it_matters": "Registry lifecycle stage drives promotion and training eligibility.",
                        },
                        "evidence": {"strategy_id": reg.strategy_id, "source_table": "strategy_registry"},
                        "linked_items": {"symbols": reg.symbols},
                    },
                },
            }

        if node_id.startswith("cluster-"):
            return {
                "status": "ok",
                "node": {
                    "id": node_id,
                    "type": "cluster",
                    "summary": "Expand cluster in graph to see child lessons.",
                },
            }

        if node_id == "hive":
            return {
                "status": "ok",
                "node": {
                    "id": "hive",
                    "title": "HIVE BRAIN",
                    "type": "hive",
                    "summary": "Collective intelligence core — consolidated lessons and broker truth.",
                },
            }

        return {"status": "error", "message": "unknown node id"}

    def _position_drawer(
        self, node_id: str, truth: dict, review: dict, reconciliation: Optional[dict] = None
    ) -> dict[str, Any]:
        display = truth.get("display_symbol") or truth.get("symbol")
        recon = reconciliation or {}
        state = recon.get("reconciliation_state", "unknown")
        labels = {
            "active_broker_position": ("Active broker position", "green", "position"),
            "broker_availability_conflict": ("Broker availability conflict", "amber", "anomaly"),
            "broker_flat_historical_order_only": ("Broker-flat — historical buy only", "slate", "historical"),
            "local_ghost_candidate": ("Local ghost candidate", "red", "anomaly"),
            "no_position": ("No open position", "slate", "resolved"),
        }
        title, ring, node_kind = labels.get(
            state, (f"{display} position (reconcile)", "slate", "anomaly")
        )
        return {
            "status": "ok",
            "node": {
                "id": node_id,
                "title": f"{display} — {title}",
                "full_label": f"{display} — {recon.get('classification', state)}",
                "type": node_kind if node_kind != "position" else "position",
                "shape": "portfolio_card",
                "category": "broker_truth",
                "color": "#06b6d4" if state == "active_broker_position" else "#64748b",
                "status": state,
                "status_ring": ring,
                "source": truth.get("data_source", "Broker Position / Position State"),
                "source_table": truth.get("source_table"),
                "source_endpoint": truth.get("source_endpoint", "/api/positions/state"),
                "source_id": truth.get("order_id"),
                "confidence": 0.95,
                "severity": "HIGH" if review.get("stale") else "MEDIUM",
                "sections": {
                    "summary": {
                        "what_this_means": self._reconciliation_summary(state, display, recon),
                        "what_ai_learned": (
                            "Quick push-pull must use true fill time for hold; broker sync is not entry time."
                        ),
                        "why_it_matters": "Training and exit rules depend on accurate hold duration.",
                        "behavior_changed": "Stale push-pull positions trigger exit recommendation and memories.",
                        "reconciliation_state": state,
                        "classification": recon.get("classification"),
                    },
                    "evidence": {
                        "reconciliation_state": state,
                        "classification": recon.get("classification"),
                        "broker_position_open": recon.get("broker_position_open"),
                        "broker_qty": recon.get("broker_qty"),
                        "available_qty": recon.get("available_qty"),
                        "local_qty": recon.get("local_qty"),
                        "historical_buy_exists": recon.get("historical_buy_exists"),
                        "historical_broker_order_id": recon.get("historical_broker_order_id"),
                        "last_exit_reject_reason": recon.get("last_exit_reject_reason"),
                        "last_exit_broker_message": recon.get("last_exit_broker_message"),
                        "broker_symbol": truth.get("broker_symbol"),
                        "display_symbol": display,
                        "qty": truth.get("qty"),
                        "avg_entry_price": truth.get("avg_entry_price"),
                        "current_price": truth.get("current_price"),
                        "unrealized_pl": truth.get("unrealized_pl"),
                        "unrealized_pl_pct": truth.get("unrealized_pl_pct"),
                        "signal_id": truth.get("signal_id"),
                        "cycle_run_id": truth.get("cycle_run_id"),
                        "strategy_name": truth.get("strategy_name"),
                        "stop_loss": truth.get("stop_loss"),
                        "take_profit": truth.get("take_profit"),
                        "broker_order_id": truth.get("broker_order_id"),
                        "client_order_id": truth.get("client_order_id"),
                        "original_filled_at": truth.get("original_filled_at"),
                        "original_entry_time": truth.get("original_entry_time"),
                        "broker_synced_at": truth.get("broker_synced_at"),
                        "true_hold_minutes": truth.get("true_hold_minutes"),
                        "hold_time_source": truth.get("hold_time_source"),
                        "hold_time_warning": truth.get("hold_time_warning"),
                        "stale_status": review.get("stale_status"),
                        "stale": review.get("stale"),
                        "action": review.get("action"),
                        "reason": review.get("reason"),
                        "broker_mode": "paper",
                        "paper_broker": True,
                        "live_trading_locked": True,
                    },
                    "linked_items": {
                        "strategies": [truth.get("strategy_name")] if truth.get("strategy_name") else [],
                        "symbols": [display],
                    },
                    "actions": [
                        "view_evidence",
                        "trace_path",
                        "open_position",
                        "rebuild_brain_graph",
                    ],
                },
            },
        }

    def _reconciliation_summary(self, state: str, display: str, recon: dict) -> str:
        if state == "active_broker_position":
            return f"Broker reports open {display} position (paper)."
        if state == "broker_availability_conflict":
            return (
                f"Broker shows {display} position but available sell qty was 0 on exit attempt. "
                "Do not retry exit until explained."
            )
        if state == "broker_flat_historical_order_only":
            return (
                f"Broker is flat for {display}. Historical buy order remains in evidence; "
                "no accepted sell fill."
            )
        if state == "local_ghost_candidate":
            return f"Local DB may show {display} open but broker truth is flat — ghost candidate for operator review."
        return f"No active broker position for {display}. Reconcile before new entries."

    def _lesson_drawer(self, detail: dict) -> dict[str, Any]:
        return {
            "status": "ok",
            "node": {
                "id": f"lesson-{detail.get('id')}",
                "title": detail.get("title"),
                "type": "lesson",
                "shape": "rounded_card",
                "sections": {
                    "summary": {
                        "what_this_means": detail.get("summary"),
                        "lesson": detail.get("detailed_lesson"),
                    },
                    "evidence": detail.get("evidence_json") or {},
                    "linked_items": {
                        "strategy": detail.get("strategy_name"),
                        "symbol": detail.get("symbol"),
                    },
                },
            },
        }
