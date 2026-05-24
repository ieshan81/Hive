"""Paper execution policy — delegates to PaperExecutionService with preflight."""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session

from app.database import ExecutionLog, PortfolioDecision
from app.services.engine_config import cfg_get
from app.services.paper_execution_service import PaperExecutionService
from app.services.portfolio_gate import ApprovedCandidate


class ExecutionPolicy:
    """Thin wrapper — limit price helpers + batch process_selected."""

    def __init__(self, session: Session, config: dict, alpaca, tier_service):
        self.session = session
        self.config = config
        self.alpaca = alpaca
        self.tiers = tier_service
        self.paper = PaperExecutionService(session, config)

    def _buffer_bps(self, tier: str) -> int:
        if "MEME" in tier:
            return int(cfg_get(self.config, "execution.limit_price_buffer_bps_meme", 40))
        if "MAJOR" in tier:
            return int(cfg_get(self.config, "execution.limit_price_buffer_bps_major", 15))
        return int(cfg_get(self.config, "execution.limit_price_buffer_bps_alt", 25))

    def limit_price(self, side: str, bid: float, ask: float, tier: str) -> float:
        bps = self._buffer_bps(tier)
        if side.lower() == "buy":
            return ask * (1 + bps / 10000.0)
        return bid * (1 - bps / 10000.0)

    def process_selected(
        self,
        cycle_run_id: str,
        selected: list[ApprovedCandidate],
        *,
        quote_by_symbol: dict[str, dict],
        portfolio_decision_by_signal: Optional[dict[int, PortfolioDecision]] = None,
        account=None,
        positions: Optional[list] = None,
        open_order_symbols: Optional[set[str]] = None,
        code_version_sha: str = "dev",
    ) -> list[ExecutionLog]:
        del code_version_sha
        logs: list[ExecutionLog] = []
        paper_enabled = bool(cfg_get(self.config, "execution.paper_orders_enabled", False))
        max_per_cycle = int(cfg_get(self.config, "execution.max_orders_per_cycle", 1))

        if not paper_enabled:
            for cand in selected[:max_per_cycle]:
                quote = quote_by_symbol.get(cand.symbol) or {}
                dec = (portfolio_decision_by_signal or {}).get(cand.signal_id)
                logs.append(
                    self.paper._log(
                        cycle_run_id,
                        cand,
                        status="approved_no_order",
                        reject_reason="PAPER_EXECUTION_DISABLED",
                        limit_price=self.limit_price(
                            cand.side,
                            quote.get("bid") or cand.entry_price,
                            quote.get("ask") or cand.entry_price,
                            cand.tier,
                        ),
                        quote=quote,
                        portfolio_decision_id=dec.id if dec else None,
                        gates_passed={"risk": True, "portfolio": True, "execution": False},
                        gates_failed={"reason": "PAPER_EXECUTION_DISABLED"},
                    )
                )
            return logs

        dec_map = portfolio_decision_by_signal or {}
        open_syms = open_order_symbols or {o.get("symbol") for o in self.alpaca.get_open_orders()}
        pos = positions or []

        for cand in selected[:max_per_cycle]:
            dec = dec_map.get(cand.signal_id)
            from app.database import StrategySignal

            sig = self.session.get(StrategySignal, cand.signal_id)
            log = self.paper.submit_candidate(
                cand,
                cycle_run_id=cycle_run_id,
                portfolio_decision=dec,
                account=account,
                positions=pos,
                open_order_symbols=open_syms,
                signal_row=sig,
            )
            logs.append(log)

        return logs
