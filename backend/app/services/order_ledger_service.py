"""Read-only normalized order ledger + FIFO paired-trade ledger for the portfolio view.

Pure normalization + FIFO pairing over the orders the bot already recorded
(``positions_tab_service.orders_history`` -> ``OrderRecord``). This module **never**
mutates a table, never places an order, and never invents values: an absent field is
``null`` and listed in ``missing_fields``. Fees are not stored on orders, so paired
trades report ``gross_pnl`` with ``estimated_fees=null`` / ``net_pnl=null`` rather than
pretending a net figure is exact.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.services.positions_tab_service import current_positions, orders_history

_KNOWN_CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "LTC", "AVAX", "LINK", "DOGE", "ADA", "XRP", "DOT",
    "MATIC", "BCH", "UNI", "AAVE", "SHIB", "USDT", "USDC", "PEPE", "TRUMP",
}
_CRYPTO_QUOTES = ("USDT", "USDC", "USD")

ORDER_TYPE_LABELS = {
    "limit_ioc": "IOC limit",
    "marketable_limit_ioc": "IOC marketable limit",
    "limit": "Limit",
    "market": "Market",
}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def normalize_symbol(symbol: str) -> str:
    """Pairing key: uppercase, alphanumeric only (BTC/USD and BTCUSD -> BTCUSD)."""
    return "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())


def classify_asset(symbol: str) -> str:
    s = str(symbol or "").upper().strip()
    if not s:
        return "unknown"
    if "/" in s or "-" in s:
        return "crypto"
    norm = normalize_symbol(s)
    for q in _CRYPTO_QUOTES:
        if norm.endswith(q) and len(norm) > len(q) and norm[: -len(q)] in _KNOWN_CRYPTO_BASES:
            return "crypto"
    if s.isalpha() and 1 <= len(s) <= 5:
        return "stock"
    return "unknown"


def display_symbol(symbol: str, asset_class: Optional[str] = None) -> str:
    s = str(symbol or "").upper().strip()
    ac = asset_class or classify_asset(s)
    if ac == "crypto":
        if "/" in s:
            return s
        norm = normalize_symbol(s)
        for q in _CRYPTO_QUOTES:
            if norm.endswith(q) and len(norm) > len(q):
                return f"{norm[:-len(q)]}/{q}"
    return s


def order_type_label(order_type: Optional[str]) -> Optional[str]:
    if not order_type:
        return None
    key = str(order_type).strip().lower()
    return ORDER_TYPE_LABELS.get(key, str(order_type).replace("_", " "))


_FILLED_STATUSES = ("filled", "paper_order_filled", "partially_filled", "paper_order_partially_filled")


def _is_filled(status: Optional[str]) -> bool:
    return str(status or "").lower() in _FILLED_STATUSES


# ───────────────────────── order ledger (TASK 3) ─────────────────────────
def _ledger_row(r: dict[str, Any]) -> dict[str, Any]:
    symbol = r.get("symbol") or ""
    asset = classify_asset(symbol)
    req_qty = _num(r.get("requested_qty"))
    filled_qty = _num(r.get("filled_qty"))
    limit_price = _num(r.get("limit_price"))
    fill_price = _num(r.get("filled_avg_price"))
    display_qty = filled_qty if filled_qty not in (None, 0) else req_qty
    display_price = fill_price if fill_price is not None else limit_price
    otype = r.get("type")
    missing: list[str] = []
    if display_qty is None:
        missing.append("qty")
    if display_price is None:
        missing.append("price")
    if not otype:
        missing.append("order_type")
    if not r.get("filled_at") and not r.get("submitted_at"):
        missing.append("timestamp")
    notional = (display_qty * display_price) if (display_qty is not None and display_price is not None) else None
    return {
        "id": r.get("id"),
        "broker_order_id": r.get("broker_order_id"),
        "client_order_id": r.get("client_order_id"),
        "symbol": symbol,
        "normalized_symbol": normalize_symbol(symbol),
        "display_symbol": display_symbol(symbol, asset),
        "asset_class": asset,
        "side": (str(r.get("side") or "").lower() or None),
        "order_type": otype,
        "order_type_label": order_type_label(otype),
        "time_in_force": r.get("tif"),
        "requested_qty": req_qty,
        "filled_qty": filled_qty,
        "display_qty": display_qty,
        "limit_price": limit_price,
        "filled_avg_price": fill_price,
        "display_price": display_price,
        "notional": round(notional, 2) if notional is not None else None,
        "status": r.get("status"),
        "broker_status": r.get("broker_status") or r.get("status"),
        "submitted_at": r.get("submitted_at"),
        "filled_at": r.get("filled_at"),
        "cycle_run_id": r.get("cycle_run_id"),
        "signal_id": r.get("signal_id"),
        "strategy": r.get("strategy") or r.get("strategy_name"),
        "reason": r.get("reason"),
        "reject_reason": r.get("reject_reason"),
        "missing_fields": missing,
    }


def build_order_ledger(session: Session, limit: int = 100) -> dict[str, Any]:
    rows = orders_history(session, limit=min(max(1, limit), 100))
    ledger = [_ledger_row(r) for r in rows]
    return {"status": "ok", "count": len(ledger), "orders": ledger}


# ───────────────────────── paired trade ledger (TASK 4) ─────────────────────────
def _ts(r: dict[str, Any]) -> str:
    return str(r.get("filled_at") or r.get("submitted_at") or "")


def build_trade_ledger(session: Session, limit: int = 100, dust_qty: float = 1e-6) -> dict[str, Any]:
    rows = orders_history(session, limit=100)
    # Broker-truth: which normalized symbols still hold an open position (else flat).
    try:
        open_norm = {
            normalize_symbol(p.get("symbol", ""))
            for p in current_positions(session)
            if _num(p.get("qty")) and _num(p.get("qty")) > 0
        }
    except Exception:
        open_norm = set()

    # Only filled orders with a usable qty + price participate in pairing.
    fills = []
    for r in rows:
        if not _is_filled(r.get("status")):
            continue
        qty = _num(r.get("filled_qty")) or _num(r.get("requested_qty"))
        price = _num(r.get("filled_avg_price")) or _num(r.get("limit_price"))
        if not qty or price is None:
            continue
        fills.append({**r, "_qty": float(qty), "_price": float(price), "_norm": normalize_symbol(r.get("symbol", ""))})
    fills.sort(key=_ts)

    by_sym: dict[str, list[dict]] = {}
    for f in fills:
        by_sym.setdefault(f["_norm"], []).append(f)

    trades: list[dict[str, Any]] = []
    tid = 0
    for norm, seq in by_sym.items():
        lots: list[dict] = []  # open buy inventory (FIFO)
        for f in seq:
            side = str(f.get("side") or "").lower()
            if side == "buy":
                lots.append({"qty": f["_qty"], "order": f})
            elif side == "sell":
                remaining = f["_qty"]
                while remaining > dust_qty and lots:
                    lot = lots[0]
                    matched = min(lot["qty"], remaining)
                    tid += 1
                    trades.append(_paired_trade(tid, norm, lot["order"], f, matched, partial=(matched < f["_qty"] or matched < lot["qty"])))
                    lot["qty"] -= matched
                    remaining -= matched
                    if lot["qty"] <= dust_qty:
                        lots.pop(0)
                if remaining > dust_qty:
                    tid += 1
                    trades.append(_unmatched_sell(tid, norm, f, remaining))
        # Leftover open buy lots: open position, or dust_residual if broker is flat.
        for lot in lots:
            if lot["qty"] <= dust_qty:
                continue
            tid += 1
            broker_flat = norm not in open_norm
            trades.append(_open_or_dust(tid, norm, lot["order"], lot["qty"], broker_flat, dust_qty))

    trades.sort(key=lambda t: t.get("exit_time") or t.get("entry_time") or "", reverse=True)
    return {
        "status": "ok",
        "count": len(trades[:limit]),
        "trades": trades[:limit],
        "summary": _ledger_summary(trades),
    }


def _hold_minutes(entry_iso: Optional[str], exit_iso: Optional[str]) -> Optional[float]:
    from datetime import datetime

    if not entry_iso or not exit_iso:
        return None
    try:
        a = datetime.fromisoformat(str(entry_iso).replace("Z", ""))
        b = datetime.fromisoformat(str(exit_iso).replace("Z", ""))
        return round(max(0.0, (b - a).total_seconds() / 60.0), 2)
    except ValueError:
        return None


def _paired_trade(tid: int, norm: str, buy: dict, sell: dict, qty: float, *, partial: bool) -> dict[str, Any]:
    bp, sp = buy["_price"], sell["_price"]
    gross = round((sp - bp) * qty, 6)
    asset = classify_asset(buy.get("symbol") or sell.get("symbol") or "")
    return {
        "trade_id": tid,
        "symbol": buy.get("symbol") or sell.get("symbol"),
        "display_symbol": display_symbol(buy.get("symbol") or "", asset),
        "asset_class": asset,
        "entry_order_id": buy.get("broker_order_id"),
        "exit_order_id": sell.get("broker_order_id"),
        "entry_time": _ts(buy) or None,
        "exit_time": _ts(sell) or None,
        "hold_minutes": _hold_minutes(_ts(buy), _ts(sell)),
        "entry_price": bp,
        "exit_price": sp,
        "qty": round(qty, 8),
        "gross_pnl": gross,
        "estimated_fees": None,  # fees are not stored on orders — do not invent
        "net_pnl": None,
        "pnl_pct": round((sp - bp) / bp * 100.0, 4) if bp else None,
        "status": "closed",
        "entry_reason": buy.get("reason") or buy.get("signal_reason"),
        "exit_reason": sell.get("reject_reason") or sell.get("reason"),
        "strategy": buy.get("strategy") or buy.get("strategy_name"),
        "signal_ids": [s for s in (buy.get("signal_id"), sell.get("signal_id")) if s is not None],
        "cycle_run_ids": [c for c in (buy.get("cycle_run_id"), sell.get("cycle_run_id")) if c],
        "pairing_confidence": "medium" if partial else "high",
    }


def _unmatched_sell(tid: int, norm: str, sell: dict, qty: float) -> dict[str, Any]:
    asset = classify_asset(sell.get("symbol") or "")
    return {
        "trade_id": tid,
        "symbol": sell.get("symbol"),
        "display_symbol": display_symbol(sell.get("symbol") or "", asset),
        "asset_class": asset,
        "entry_order_id": None,
        "exit_order_id": sell.get("broker_order_id"),
        "entry_time": None,
        "exit_time": _ts(sell) or None,
        "hold_minutes": None,
        "entry_price": None,
        "exit_price": sell["_price"],
        "qty": round(qty, 8),
        "gross_pnl": None,
        "estimated_fees": None,
        "net_pnl": None,
        "pnl_pct": None,
        "status": "unmatched",
        "entry_reason": None,
        "exit_reason": sell.get("reject_reason") or sell.get("reason"),
        "strategy": sell.get("strategy"),
        "signal_ids": [s for s in (sell.get("signal_id"),) if s is not None],
        "cycle_run_ids": [c for c in (sell.get("cycle_run_id"),) if c],
        "pairing_confidence": "low",
    }


def _open_or_dust(tid: int, norm: str, buy: dict, qty: float, broker_flat: bool, dust_qty: float) -> dict[str, Any]:
    asset = classify_asset(buy.get("symbol") or "")
    # Broker flat + small residual -> the position is effectively closed (crypto fee/dust).
    is_dust = broker_flat and qty <= max(dust_qty * 1000, 0.01)
    return {
        "trade_id": tid,
        "symbol": buy.get("symbol"),
        "display_symbol": display_symbol(buy.get("symbol") or "", asset),
        "asset_class": asset,
        "entry_order_id": buy.get("broker_order_id"),
        "exit_order_id": None,
        "entry_time": _ts(buy) or None,
        "exit_time": None,
        "hold_minutes": None,
        "entry_price": buy["_price"],
        "exit_price": None,
        "qty": round(qty, 8),
        "gross_pnl": None,
        "estimated_fees": None,
        "net_pnl": None,
        "pnl_pct": None,
        "status": "dust_residual" if (is_dust or broker_flat) else "open",
        "entry_reason": buy.get("reason"),
        "exit_reason": None,
        "strategy": buy.get("strategy"),
        "signal_ids": [s for s in (buy.get("signal_id"),) if s is not None],
        "cycle_run_ids": [c for c in (buy.get("cycle_run_id"),) if c],
        "pairing_confidence": "low" if broker_flat else "medium",
    }


def _ledger_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if t["status"] == "closed"]
    gross_vals = [t["gross_pnl"] for t in closed if t["gross_pnl"] is not None]
    wins = [g for g in gross_vals if g > 0]
    has_fees = any(t.get("estimated_fees") is not None for t in closed)
    biggest_win = max(gross_vals) if gross_vals else None
    biggest_loss = min(gross_vals) if gross_vals else None
    return {
        "closed_trades": len(closed),
        "gross_pnl": round(sum(gross_vals), 4) if gross_vals else (0.0 if closed else None),
        "estimated_net_pnl": None if not has_fees else round(sum((t["net_pnl"] or 0) for t in closed), 4),
        "win_rate_pct": round(len(wins) / len(gross_vals) * 100.0, 1) if gross_vals else None,
        "biggest_winner": round(biggest_win, 4) if biggest_win is not None else None,
        "biggest_loser": round(biggest_loss, 4) if biggest_loss is not None else None,
        "open_positions": len([t for t in trades if t["status"] == "open"]),
        "dust_residual_count": len([t for t in trades if t["status"] == "dust_residual"]),
        "unmatched_count": len([t for t in trades if t["status"] == "unmatched"]),
        "fees_available": has_fees,
    }
