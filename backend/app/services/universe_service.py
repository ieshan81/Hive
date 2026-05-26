"""Operator universe — symbols the bot can scan and trade."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.database import PaperExperimentDecision, SymbolCandidate
from app.services.account_pair_eligibility_service import AccountPairEligibilityService
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import get_latest_reset_epoch, record_created_after


def universe_status(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    cfg = config or ConfigManager(session).get_current()
    epoch = get_latest_reset_epoch(session)
    elig_svc = AccountPairEligibilityService(session, cfg)
    elig = elig_svc.summary()

    pair_by_sym: dict[str, dict] = {}
    for row in (elig.get("eligible") or []) + (elig.get("blocked") or []):
        pair_by_sym[row.get("symbol", "")] = row

    candidates = list(
        session.exec(select(SymbolCandidate).order_by(SymbolCandidate.scanned_at.desc()).limit(200)).all()
    )
    decisions = list(
        session.exec(
            select(PaperExperimentDecision).order_by(PaperExperimentDecision.created_at.desc()).limit(100)
        ).all()
    )
    if epoch:
        cutoff = epoch.get("nuke_completed_at")
        decisions = [d for d in decisions if record_created_after(d, cutoff)]

    stock: list[dict] = []
    crypto: list[dict] = []
    active: list[dict] = []
    blocked: list[dict] = []
    watch: list[dict] = []

    seen: set[str] = set()
    for c in candidates:
        if c.symbol in seen:
            continue
        seen.add(c.symbol)
        row = _symbol_row(c, pair_by_sym.get(c.symbol), decisions)
        ac = (c.asset_class or "stock").lower()
        if ac == "crypto":
            crypto.append(row)
        else:
            stock.append(row)
        if row["status"] == "Active":
            active.append(row)
        elif row["status"] == "Blocked":
            blocked.append(row)
        else:
            watch.append(row)

    for sym, pair in pair_by_sym.items():
        if sym in seen:
            continue
        row = _symbol_row_from_pair(sym, pair, decisions)
        if "/" in sym:
            crypto.append(row)
        else:
            stock.append(row)
        if row["status"] == "Active":
            active.append(row)
        elif row["status"] == "Blocked":
            blocked.append(row)
        else:
            watch.append(row)

    return {
        "status": "ok",
        "reset_epoch": epoch,
        "groups": {
            "stock_universe": stock[:50],
            "crypto_universe": crypto[:50],
            "active_push_pull_candidates": active[:30],
            "blocked_unsupported": blocked[:40],
            "watch_only": watch[:30],
            "recently_rejected": _recent_rejected(decisions)[:30],
        },
        "counts": {
            "stock": len(stock),
            "crypto": len(crypto),
            "active": len(active),
            "blocked": len(blocked),
        },
        "eligibility_summary": elig,
    }


def _symbol_row(c: SymbolCandidate, pair: Optional[dict], decisions: list) -> dict[str, Any]:
    sym = c.symbol
    pair = pair or {}
    last_dec = next((d for d in decisions if d.symbol == sym), None)
    eligible = pair.get("status") == "eligible" or c.eligibility == "eligible"
    score = float(c.liquidity_score or 0) + float(c.sentiment_score or 0) * 0.3
    status = "Active" if eligible and score >= 30 else "Blocked"
    if not eligible:
        status = "Blocked"
    elif score < 20:
        status = "Watch-only"

    bal = elig_balances(pair)
    return {
        "symbol": sym,
        "asset_type": "Crypto" if (c.asset_class or "").lower() == "crypto" else "Stock",
        "status": status,
        "tradable_now": eligible and status == "Active",
        "blocked_reason": pair.get("reason") if not eligible else None,
        "quote_currency": pair.get("quote_currency"),
        "funding_usd": bal.get("USD"),
        "funding_usdc": bal.get("USDC"),
        "funding_usdt": bal.get("USDT"),
        "broker_eligible": eligible,
        "quote_freshness": "fresh" if c.scanned_at else "unknown",
        "spread_pct": c.spread_pct,
        "liquidity_score": c.liquidity_score,
        "last_scan_at": c.scanned_at.isoformat() + "Z" if c.scanned_at else None,
        "last_decision": last_dec.decision if last_dec else None,
        "last_decision_reason": last_dec.reason_code if last_dec else None,
        "strategy_enabled": True,
        "score": round(score, 1),
    }


def _symbol_row_from_pair(sym: str, pair: dict, decisions: list) -> dict[str, Any]:
    last_dec = next((d for d in decisions if d.symbol == sym), None)
    eligible = pair.get("status") == "eligible"
    status = "Active" if eligible else "Blocked"
    return {
        "symbol": sym,
        "asset_type": "Crypto" if "/" in sym else "Stock",
        "status": status,
        "tradable_now": eligible,
        "blocked_reason": pair.get("reason"),
        "quote_currency": pair.get("quote_currency"),
        "funding_usd": None,
        "funding_usdc": None,
        "funding_usdt": None,
        "broker_eligible": eligible,
        "quote_freshness": "unknown",
        "spread_pct": None,
        "liquidity_score": None,
        "last_scan_at": None,
        "last_decision": last_dec.decision if last_dec else None,
        "last_decision_reason": last_dec.reason_code if last_dec else None,
        "strategy_enabled": True,
        "score": None,
    }


def elig_balances(pair: dict) -> dict[str, Optional[float]]:
    return {"USD": None, "USDC": None, "USDT": None}


def _recent_rejected(decisions: list) -> list[dict]:
    out = []
    for d in decisions:
        if d.decision != "approved":
            out.append(
                {
                    "symbol": d.symbol,
                    "reason_code": d.reason_code,
                    "reason_text": d.reason_text,
                    "created_at": d.created_at.isoformat() + "Z" if d.created_at else None,
                }
            )
    return out
