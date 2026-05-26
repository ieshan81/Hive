"""Capital Allocator Formula — paper-only exposure and session-aware budget distribution."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot, ExecutionLog, OrderRecord, PositionSnapshot
from app.services.account_pair_eligibility_service import (
    AccountPairEligibilityService,
    parse_quote_currency,
)
from app.services.alpaca_adapter import AlpacaAdapter
from app.services.broker_safety import is_paper_broker_url
from app.services.config_manager import ConfigManager
from app.services.engine_config import cfg_get
from app.services.session_engine import CRYPTO_STRATEGIES, STOCK_STRATEGIES, SessionEngine

MARKET_MODES = (
    "US_STOCK_OPEN",
    "US_STOCK_AFTER_HOURS",
    "US_STOCK_NEAR_CLOSE",
    "CRYPTO_NIGHT",
    "WEEKEND_CRYPTO",
    "HOLIDAY_CRYPTO_ONLY",
    "DEGRADED_BROKER_DATA",
)

MEME_PATTERN = re.compile(r"DOGE|SHIB|PEPE|BONK|TRUMP|MEME", re.I)


def _cfg(config: dict) -> dict:
    return dict(config.get("capital_allocator") or {})


def _unlimited(val: Any) -> bool:
    """0, None, or negative means no artificial cap."""
    if val is None:
        return True
    try:
        return int(val) <= 0
    except (TypeError, ValueError):
        return False


class CapitalAllocatorService:
    def __init__(self, session: Session, config: Optional[dict] = None):
        self.session = session
        self.config = config or ConfigManager(session).get_current()
        self.cfg = _cfg(self.config)
        self.alpaca = AlpacaAdapter(session)
        self.session_engine = SessionEngine()
        self.eligibility = AccountPairEligibilityService(session, self.config)

    def settings(self) -> dict[str, Any]:
        return {"status": "ok", "settings": self.cfg, "paper_only": True}

    def update_settings(self, patch: dict, operator: str = "operator") -> dict[str, Any]:
        cfg_mgr = ConfigManager(self.session)
        cur = cfg_mgr.get_current()
        merged = {**cur, "capital_allocator": {**(cur.get("capital_allocator") or {}), **patch}}
        cfg_mgr._activate(merged, operator, "capital_allocator_settings")
        self.config = cfg_mgr.get_current()
        self.cfg = _cfg(self.config)
        return self.settings()

    def _detect_market_mode(self, sess) -> str:
        if getattr(self.alpaca, "broker_sync_rate_limited", False):
            snap = self.session.exec(
                select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())
            ).first()
            if not snap:
                return "DEGRADED_BROKER_DATA"
        if not is_paper_broker_url():
            return "DEGRADED_BROKER_DATA"

        if not sess.calendar_available:
            return "HOLIDAY_CRYPTO_ONLY" if sess.crypto_trading_allowed else "DEGRADED_BROKER_DATA"
        if sess.is_weekend:
            return "WEEKEND_CRYPTO"
        if sess.us_stock_close_reason and "holiday" in (sess.us_stock_close_reason or "").lower():
            return "HOLIDAY_CRYPTO_ONLY"

        close_cutoff = int(self.cfg.get("stock_close_cutoff_minutes", 45))
        try:
            from zoneinfo import ZoneInfo

            now_ny = datetime.now(ZoneInfo("America/New_York"))
            t = now_ny.time()
            close_t = SessionEngine.MARKET_CLOSE
            mins_to_close = (
                (close_t.hour * 60 + close_t.minute) - (t.hour * 60 + t.minute)
            )
            if 0 < mins_to_close <= close_cutoff and sess.us_stock_session == "open":
                return "US_STOCK_NEAR_CLOSE"
        except Exception:
            pass

        if sess.us_stock_session == "open":
            return "US_STOCK_OPEN"
        if sess.us_stock_session in ("afterhours", "premarket"):
            return "US_STOCK_AFTER_HOURS"
        if sess.is_night_mode or sess.us_stock_session == "closed":
            return "CRYPTO_NIGHT"
        return "CRYPTO_NIGHT"

    def _account_state(self) -> dict[str, Any]:
        snap = self.alpaca.sync_account_cached()
        if not snap:
            snap = self.session.exec(
                select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())
            ).first()
        equity = float(snap.equity or 0) if snap else 0.0
        cash = float(snap.cash or 0) if snap else 0.0
        bp = float(snap.buying_power or cash) if snap else 0.0
        return {
            "equity": equity,
            "cash": cash,
            "buying_power": bp,
            "snapshot": snap,
            "broker_fresh": not bool(self.alpaca.broker_sync_rate_limited),
        }

    def _pending_order_reserve(self) -> float:
        pending = list(
            self.session.exec(
                select(OrderRecord).where(
                    OrderRecord.status.in_(("pending", "new", "accepted", "partially_filled"))
                )
            ).all()
        )
        total = 0.0
        for o in pending:
            notional = float(o.qty or 0) * float(o.limit_price or o.filled_avg_price or 0)
            if notional <= 0 and o.qty:
                notional = float(o.qty) * 1.0
            total += notional
        return total

    def _exposure_by_class(self) -> tuple[float, float, list[dict]]:
        stock_exp, crypto_exp = 0.0, 0.0
        rows = []
        for pos in self.session.exec(select(PositionSnapshot).where(PositionSnapshot.qty > 0)).all():
            mv = abs(float(pos.market_value or 0))
            if mv <= 0:
                mv = abs(float(pos.qty or 0) * float(pos.current_price or pos.avg_entry_price or 0))
            sym = pos.symbol or ""
            is_crypto = "/" in sym or sym.upper().endswith("USD") and len(sym) > 6
            if any(sym.upper().startswith(c.replace("/", "")) for c in ("BTC", "ETH", "SOL")) or "/" in sym:
                is_crypto = True
            if is_crypto:
                crypto_exp += mv
            else:
                stock_exp += mv
            rows.append({"symbol": sym, "market_value": mv, "asset_class": "crypto" if is_crypto else "stock"})
        return stock_exp, crypto_exp, rows

    def _session_weights(self, market_mode: str) -> tuple[float, float, float]:
        sw = float(self.cfg.get("stock_target_weight", 0.35))
        cw = float(self.cfg.get("crypto_target_weight", 0.45))
        reserve_w = float(self.cfg.get("cash_reserve_weight", 0.20))
        night_boost = float(self.cfg.get("crypto_night_reserve_weight", 0.15))

        if market_mode == "US_STOCK_OPEN":
            if self.cfg.get("allow_crypto_during_stock_hours", True):
                return sw, cw, reserve_w
            return sw, cw * 0.5, reserve_w + cw * 0.5
        if market_mode == "US_STOCK_NEAR_CLOSE":
            return sw * 0.4, cw + night_boost, reserve_w
        if market_mode in ("CRYPTO_NIGHT", "WEEKEND_CRYPTO", "HOLIDAY_CRYPTO_ONLY", "US_STOCK_AFTER_HOURS"):
            return sw * 0.1 if self.cfg.get("allow_stocks_after_hours", False) else 0.0, cw + night_boost, reserve_w
        if market_mode == "DEGRADED_BROKER_DATA":
            return 0.0, 0.0, 1.0
        return sw, cw, reserve_w

    def build_plan(self, signals: Optional[list[dict]] = None) -> dict[str, Any]:
        sess = self.session_engine.detect()
        market_mode = self._detect_market_mode(sess)
        acct = self._account_state()
        stock_exp, crypto_exp, pos_rows = self._exposure_by_class()
        pending_res = self._pending_order_reserve()
        equity = acct["equity"]
        bp = acct["buying_power"]
        uncertainty = float(self.cfg.get("broker_uncertainty_buffer_pct", 0.05)) * bp if bp else 0.0

        sw, cw, reserve_w = self._session_weights(market_mode)
        cash_reserve = max(
            float(self.cfg.get("min_cash_reserve", 25)),
            equity * reserve_w,
        )
        deployable = max(0.0, bp - pending_res - cash_reserve - uncertainty)

        stock_budget = deployable * sw
        crypto_budget = deployable * cw
        overnight_crypto_reserve = deployable * float(self.cfg.get("crypto_night_reserve_weight", 0.15))
        if market_mode in ("US_STOCK_NEAR_CLOSE", "CRYPTO_NIGHT", "WEEKEND_CRYPTO"):
            stock_budget *= 0.6
            crypto_budget = max(crypto_budget, overnight_crypto_reserve)

        stock_budget = max(0.0, stock_budget - stock_exp)
        crypto_budget = max(0.0, crypto_budget - crypto_exp)

        max_stock_class = deployable * float(self.cfg.get("max_asset_class_exposure_weight", 0.55))
        max_crypto_class = deployable * float(self.cfg.get("max_asset_class_exposure_weight", 0.55))
        stock_budget = min(stock_budget, max(0, max_stock_class - stock_exp))
        crypto_budget = min(crypto_budget, max(0, max_crypto_class - crypto_exp))

        blocked_symbols = []
        elig_summary = {}
        try:
            elig_summary = self.eligibility.summary()
            for row in elig_summary.get("blocked", []):
                blocked_symbols.append(
                    {
                        "symbol": row.get("symbol"),
                        "reason": row.get("reason"),
                        "category": row.get("category"),
                    }
                )
        except Exception as exc:
            blocked_symbols.append({"symbol": "*", "reason": str(exc), "category": "eligibility_error"})

        per_symbol = self._per_symbol_allocations(
            signals or [],
            stock_budget,
            crypto_budget,
            market_mode,
            blocked_symbols,
        )

        diversification = self._diversification_health(
            stock_exp, crypto_exp, deployable, stock_budget, crypto_budget, per_symbol
        )

        degraded = market_mode == "DEGRADED_BROKER_DATA" or not acct["broker_fresh"]
        warnings = []
        if degraded:
            warnings.append("Broker sync temporarily rate-limited or unavailable — execution blocked until fresh.")
        if deployable <= 0 and not degraded:
            warnings.append("No deployable capital after reserves and open exposure.")

        return {
            "status": "degraded" if degraded else "ok",
            "paper_only": True,
            "live_trading_locked": True,
            "current_market_mode": market_mode,
            "broker_data_freshness": "fresh" if acct["broker_fresh"] else "stale_rate_limited",
            "session": sess.to_dict(),
            "total_equity": round(equity, 2),
            "cash": round(acct["cash"], 2),
            "buying_power": round(bp, 2),
            "deployable_capital": round(deployable, 2),
            "reserved_for_open_orders": round(pending_res, 2),
            "required_cash_reserve": round(cash_reserve, 2),
            "broker_uncertainty_buffer": round(uncertainty, 2),
            "stock_allocation_budget": round(stock_budget, 2),
            "crypto_allocation_budget": round(crypto_budget, 2),
            "cash_reserve_budget": round(cash_reserve, 2),
            "stock_hold_budget": round(stock_budget, 2),
            "crypto_push_pull_budget": round(crypto_budget, 2),
            "overnight_crypto_reserve": round(overnight_crypto_reserve, 2),
            "current_stock_exposure": round(stock_exp, 2),
            "current_crypto_exposure": round(crypto_exp, 2),
            "per_asset_class_exposure": {
                "stock": round(stock_exp, 2),
                "crypto": round(crypto_exp, 2),
            },
            "open_positions": pos_rows,
            "per_symbol_budget": per_symbol,
            "blocked_symbols": blocked_symbols,
            "diversification_health": diversification,
            "degraded_warnings": warnings,
            "reason_codes": self._plan_reason_codes(market_mode, deployable, diversification),
            "learning_capacity": {
                "mode": "opportunity_based",
                "daily_paper_trade_cap": None if _unlimited(self.config.get("autonomous_paper_learning", {}).get("max_paper_trades_per_day")) else "capped",
                "position_control": "allocator_exposure",
                "max_open_positions_cap": None if _unlimited(self.cfg.get("operator_emergency_max_open_positions")) else self.cfg.get("operator_emergency_max_open_positions"),
            },
        }

    def _plan_reason_codes(self, market_mode: str, deployable: float, diversification: dict) -> list[str]:
        codes = [f"market_mode:{market_mode}"]
        if deployable > 0:
            codes.append("deployable_capital_available")
        if diversification.get("healthy"):
            codes.append("diversification_ok")
        else:
            codes.append("diversification_watch")
        return codes

    def _diversification_health(
        self,
        stock_exp: float,
        crypto_exp: float,
        deployable: float,
        stock_budget: float,
        crypto_budget: float,
        per_symbol: list[dict],
    ) -> dict[str, Any]:
        max_single_stock = float(self.cfg.get("max_single_stock_exposure_weight", 0.25))
        max_single_crypto = float(self.cfg.get("max_single_crypto_exposure_weight", 0.25))
        max_class = float(self.cfg.get("max_asset_class_exposure_weight", 0.55))
        issues = []
        if deployable > 0:
            if stock_exp / deployable > max_class:
                issues.append("stock_class_concentration")
            if crypto_exp / deployable > max_class:
                issues.append("crypto_class_concentration")
        for row in per_symbol:
            cap = row.get("approved_notional") or 0
            ac = row.get("asset_class")
            if ac == "stock" and stock_budget > 0 and cap > stock_budget * max_single_stock:
                issues.append(f"single_stock_cap:{row.get('symbol')}")
            if ac == "crypto" and crypto_budget > 0 and cap > crypto_budget * max_single_crypto:
                issues.append(f"single_crypto_cap:{row.get('symbol')}")
        return {
            "healthy": len(issues) == 0,
            "issues": issues,
            "concentration_score": round(100 - len(issues) * 15, 1),
        }

    def _symbol_asset_class(self, symbol: str, strategy_id: str = "") -> str:
        if strategy_id in CRYPTO_STRATEGIES or "/" in symbol:
            return "crypto"
        if strategy_id in STOCK_STRATEGIES:
            return "stock"
        if "/" in symbol or parse_quote_currency(symbol) in ("USDC", "USDT", "BTC", "ETH"):
            return "crypto"
        return "stock"

    def _per_symbol_allocations(
        self,
        signals: list[dict],
        stock_budget: float,
        crypto_budget: float,
        market_mode: str,
        blocked: list[dict],
    ) -> list[dict]:
        blocked_set = {b.get("symbol") for b in blocked}
        stock_signals, crypto_signals = [], []
        for sig in signals:
            sym = sig.get("symbol") or ""
            if sym in blocked_set:
                continue
            ac = self._symbol_asset_class(sym, sig.get("strategy_id", ""))
            entry = {**sig, "asset_class": ac}
            if ac == "crypto":
                crypto_signals.append(entry)
            else:
                stock_signals.append(entry)

        out = []
        out.extend(self._allocate_class(stock_signals, stock_budget, "stock", market_mode))
        out.extend(self._allocate_class(crypto_signals, crypto_budget, "crypto", market_mode))
        return out

    def _allocate_class(
        self, signals: list[dict],
        class_budget: float,
        asset_class: str,
        market_mode: str,
    ) -> list[dict]:
        if class_budget <= 0 or not signals:
            return []
        scored = []
        for sig in signals:
            sym = sig.get("symbol") or ""
            score = self._signal_score(sig, asset_class, market_mode)
            scored.append({**sig, "raw_score": score})
        if not scored:
            return []
        total = sum(max(0.01, s["raw_score"]) for s in scored)
        max_single = float(
            self.cfg.get(
                "max_single_crypto_exposure_weight" if asset_class == "crypto" else "max_single_stock_exposure_weight",
                0.25,
            )
        )
        cap_per_symbol = class_budget * max_single
        results = []
        for s in scored:
            share = s["raw_score"] / total
            notional = min(cap_per_symbol, class_budget * share)
            results.append(
                {
                    "symbol": s.get("symbol"),
                    "strategy_id": s.get("strategy_id"),
                    "asset_class": asset_class,
                    "score": round(s["raw_score"], 3),
                    "share_pct": round(share * 100, 2),
                    "approved_notional": round(notional, 2),
                    "reason": f"Proportional {asset_class} allocation ({market_mode})",
                }
            )
        return results

    def _signal_score(self, sig: dict, asset_class: str, market_mode: str) -> float:
        base = float(sig.get("strength") or sig.get("confidence") or 50)
        momentum = float(sig.get("momentum_score") or 0)
        conf = float(sig.get("confidence_score") or base)
        session_bonus = 10.0 if asset_class == "crypto" and market_mode.startswith("CRYPTO") else 0.0
        session_bonus += 10.0 if asset_class == "stock" and market_mode == "US_STOCK_OPEN" else 0.0
        spread_pen = float(sig.get("spread_pct") or 0) * 5
        vol_pen = float(sig.get("volatility_penalty") or 0)
        meme_pen = 15.0 if sig.get("symbol") and MEME_PATTERN.search(sig.get("symbol", "")) else 0.0
        corr_pen = float(sig.get("correlation_penalty") or 0)
        reject_pen = float(sig.get("reject_penalty") or 0)
        quote_pen = float(sig.get("quote_penalty") or 0)
        return max(0.01, base + momentum + conf * 0.2 + session_bonus - spread_pen - vol_pen - meme_pen - corr_pen - reject_pen - quote_pen)

    def approve_trade(
        self,
        symbol: str,
        side: str,
        strategy_id: str,
        requested_notional: float,
        *,
        signal_meta: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Return approval for a single trade — used by paper preflight."""
        plan = self.build_plan(signals=[signal_meta] if signal_meta else [])
        if plan.get("status") == "degraded" or plan.get("broker_data_freshness") != "fresh":
            return {
                "approved": False,
                "approved_notional": 0.0,
                "reason_code": "allocator_degraded",
                "reason": "Capital allocator degraded — unknown buying power",
                "plan": plan,
            }

        if side.lower() != "buy":
            return {"approved": True, "approved_notional": requested_notional, "reason_code": "sell_exempt", "plan": plan}

        elig = self.eligibility.preflight_block(symbol, side, strategy_id)
        if elig:
            return {
                "approved": False,
                "approved_notional": 0.0,
                "reason_code": elig[0],
                "reason": elig[1],
                "plan": plan,
            }

        ac = self._symbol_asset_class(symbol, strategy_id)
        class_budget = (
            plan.get("stock_allocation_budget", 0)
            if ac == "stock"
            else plan.get("crypto_allocation_budget", 0)
        )
        max_single = float(
            self.cfg.get(
                "max_single_crypto_exposure_weight" if ac == "crypto" else "max_single_stock_exposure_weight",
                0.25,
            )
        )
        cap = class_budget * max_single
        approved = min(requested_notional, cap, plan.get("deployable_capital", 0) * max_single)
        if approved < float(self.cfg.get("min_trade_notional_usd", 1)):
            return {
                "approved": False,
                "approved_notional": 0.0,
                "reason_code": "below_min_notional",
                "reason": "Approved notional below minimum",
                "plan": plan,
            }
        if approved < requested_notional * 0.5:
            return {
                "approved": True,
                "approved_notional": round(approved, 2),
                "reason_code": "allocator_capped",
                "reason": f"Allocator capped to ${approved:.2f} for diversification",
                "plan": plan,
            }
        return {
            "approved": True,
            "approved_notional": round(approved, 2),
            "reason_code": "allocator_approved",
            "reason": "Capital allocator approved",
            "plan": plan,
        }

    def status_summary(self) -> dict[str, Any]:
        plan = self.build_plan()
        return {
            "status": plan.get("status", "ok"),
            "allocator_confidence": plan.get("diversification_health", {}).get("concentration_score", 50),
            "current_market_mode": plan.get("current_market_mode"),
            "deployable_capital": plan.get("deployable_capital"),
            "diversification_health": plan.get("diversification_health"),
            "broker_data_freshness": plan.get("broker_data_freshness"),
            "degraded_warnings": plan.get("degraded_warnings", []),
            "learning_capacity": plan.get("learning_capacity"),
        }

    def recent_decisions(self, limit: int = 30) -> list[dict]:
        rows = list(
            self.session.exec(
                select(ExecutionLog).order_by(ExecutionLog.id.desc()).limit(limit)
            ).all()
        )
        return [
            {
                "symbol": r.symbol,
                "status": r.status,
                "side": r.side,
                "reject_reason": r.reject_reason,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]
