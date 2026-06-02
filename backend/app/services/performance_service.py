"""Paper performance — equity curve and summary (post-reset aware)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import AccountSnapshot, TradeRecord
from app.services.config_manager import ConfigManager
from app.services.nuke_epoch_service import (
    PAPER_BASELINE_EQUITY,
    PAPER_VALIDATION_RUN_ID,
    get_latest_reset_epoch,
)


def _run_baseline(epoch: Optional[dict], fallback_equity: float) -> float:
    """Reporting baseline for the active run: the epoch's pinned baseline equity
    (defaulting to the funded $200 paper baseline) — never the moving current equity."""
    if epoch:
        b = epoch.get("baseline_equity")
        return float(b) if b is not None else float(PAPER_BASELINE_EQUITY)
    return float(fallback_equity)


def _run_id(epoch: Optional[dict]) -> Optional[str]:
    if not epoch:
        return None
    return epoch.get("validation_run_id") or PAPER_VALIDATION_RUN_ID


def performance_summary(session: Session, config: Optional[dict] = None) -> dict[str, Any]:
    epoch = get_latest_reset_epoch(session)
    snap = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()
    equity = float(snap.equity if snap else 0)
    cash = float(snap.cash if snap else 0)

    trades = _post_nuke_trades(session, epoch)
    closed = [t for t in trades if t.status == "closed"]
    wins = [t for t in closed if (t.return_pct or 0) > 0 or (t.pl_dollars or 0) > 0]
    pl = sum(float(t.pl_dollars or 0) for t in closed)

    baseline = _run_baseline(epoch, equity)
    run_id = _run_id(epoch)
    label = "Fresh paper baseline after reset"
    if run_id:
        label = f"{run_id} — paper validation run (baseline ${baseline:.0f})"
    elif epoch:
        label = f"Post-reset paper performance since {epoch.get('nuke_completed_at', 'reset')}"

    return {
        "status": "ok",
        "reset_epoch": epoch,
        "validation_run_id": run_id,
        "baseline_equity": round(baseline, 2),
        "fresh_baseline_label": label,
        "current_equity": round(equity, 2),
        "cash": round(cash, 2),
        "starting_equity": round(baseline, 2),
        "pl_dollars": round(pl, 2),
        "return_pct": round((equity - baseline) / baseline * 100, 3) if baseline > 0 else None,
        "trades_count": len(trades),
        "closed_trades": len(closed),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "expectancy": round(pl / len(closed), 2) if closed else None,
        "post_nuke_only": bool(epoch),
    }


def equity_curve(session: Session, limit: int = 120) -> dict[str, Any]:
    epoch = get_latest_reset_epoch(session)
    snaps = list(session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.asc())).all())
    if epoch and epoch.get("nuke_completed_at"):
        try:
            cutoff = datetime.fromisoformat(str(epoch["nuke_completed_at"]).replace("Z", ""))
            snaps = [s for s in snaps if s.synced_at and s.synced_at >= cutoff]
        except ValueError:
            pass

    points = [
        {
            "t": s.synced_at.isoformat() + "Z" if s.synced_at else None,
            "equity": round(float(s.equity or 0), 2),
            "cash": round(float(s.cash or 0), 2),
        }
        for s in snaps[-limit:]
    ]
    if not points and session.exec(select(AccountSnapshot)).first():
        s = session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()
        points = [
            {
                "t": s.synced_at.isoformat() + "Z" if s.synced_at else None,
                "equity": round(float(s.equity or 0), 2),
                "cash": round(float(s.cash or 0), 2),
            }
        ]

    # Anchor the curve at the funded run baseline ($200) so the validation run's equity
    # curve starts at the true reset baseline rather than the first recorded snapshot dip.
    run_id = _run_id(epoch)
    baseline = _run_baseline(epoch, float(points[0]["equity"]) if points else 0.0)
    if epoch and (not points or abs(float(points[0]["equity"]) - baseline) > 0.01):
        anchor_t = epoch.get("nuke_completed_at") or (points[0]["t"] if points else None)
        points = [{"t": anchor_t, "equity": round(baseline, 2), "cash": round(baseline, 2), "baseline": True}] + points

    # Drawdown overlay + change summary for the cockpit Portfolio History card.
    peak: Optional[float] = None
    max_dd = 0.0
    for p in points:
        eq = float(p.get("equity") or 0)
        peak = eq if peak is None else max(peak, eq)
        dd = ((peak - eq) / peak * 100.0) if peak and peak > 0 else 0.0
        p["drawdown_pct"] = round(dd, 3)
        max_dd = max(max_dd, dd)
    start_equity = round(baseline, 2) if epoch else (float(points[0]["equity"]) if points else 0.0)
    current_equity = float(points[-1]["equity"]) if points else 0.0

    return {
        "status": "ok",
        "reset_epoch": epoch,
        "validation_run_id": run_id,
        "baseline_equity": round(baseline, 2),
        "fresh_baseline_label": f"{run_id} baseline ${baseline:.0f}" if run_id else "Fresh paper baseline after reset",
        "points": points,
        "count": len(points),
        "start_equity": round(start_equity, 2),
        "current_equity": round(current_equity, 2),
        "change_usd": round(current_equity - start_equity, 2),
        "change_pct": round((current_equity - start_equity) / start_equity * 100.0, 3) if start_equity > 0 else None,
        "max_drawdown_pct": round(max_dd, 3),
    }


def _post_nuke_trades(session: Session, epoch: Optional[dict]) -> list[TradeRecord]:
    rows = list(session.exec(select(TradeRecord)).all())
    if not epoch or not epoch.get("nuke_completed_at"):
        return rows
    cutoff = epoch["nuke_completed_at"]
    try:
        cut = datetime.fromisoformat(str(cutoff).replace("Z", ""))
    except ValueError:
        return rows
    # Crash-safe timestamp resolution: a trade with a None created_at still resolves
    # via opened_at/closed_at (etc.) instead of being silently dropped.
    from app.services.timestamp_safety import safe_record_timestamp

    out: list[TradeRecord] = []
    for t in rows:
        ts = safe_record_timestamp(t)
        if ts is not None and ts >= cut:
            out.append(t)
    return out
