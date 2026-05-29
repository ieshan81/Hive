"""
Safe READ-ONLY API snapshot collection for the diagnostic bundle.

Each snapshot captures the JSON response of a known-safe GET endpoint into a
file in `api_snapshots/`. Failures are recorded but never crash the bundle.

Rules (Phase 2 spec):
  - No POST. No mutation. No cycle run.
  - No provider fetch (the snapshots reuse in-process services where possible).
  - No order submission. No Gemini call.
  - Per-snapshot timeout. Errors recorded, not raised.

Each output JSON:
  {
    endpoint, captured_at_utc, status_code | null,
    response_json | error, timeout_ms, read_only: True
  }
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Callable, Optional

from sqlmodel import Session

logger = logging.getLogger(__name__)


SNAPSHOT_TIMEOUT_MS = 4000  # per snapshot soft budget
_API_SNAPSHOT_DIR = "api_snapshots"


def _snapshot_envelope(
    *,
    endpoint: str,
    response: Any = None,
    error: Optional[str] = None,
    status_code: Optional[int] = 200,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "endpoint": endpoint,
        "captured_at_utc": datetime.utcnow().isoformat() + "Z",
        "status_code": status_code if error is None else None,
        "timeout_ms": SNAPSHOT_TIMEOUT_MS,
        "elapsed_ms": elapsed_ms,
        "read_only": True,
    }
    if error is not None:
        out["error"] = error[:500]
        out["status_code"] = None
    else:
        out["response_json"] = response
    return out


def _safe_call(endpoint: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.time()
    try:
        result = fn()
        elapsed_ms = int((time.time() - started) * 1000)
        return _snapshot_envelope(endpoint=endpoint, response=result, elapsed_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        logger.debug("api_snapshot failed for %s: %s", endpoint, exc)
        return _snapshot_envelope(endpoint=endpoint, error=str(exc), elapsed_ms=elapsed_ms)


# ──────────────────────────────────────────────────────────────────────
# Per-endpoint collectors (in-process — no HTTP loopback to avoid races)
# ──────────────────────────────────────────────────────────────────────

def _collect_health() -> dict[str, Any]:
    # Same logic as /health, computed without an HTTP roundtrip
    from app.config import settings
    warnings = []
    if not settings.alpaca_configured:
        warnings.append("Alpaca credentials missing")
    if not settings.gemini_configured:
        warnings.append("Gemini API key missing")
    return {
        "status": "ok",
        "service": "caged-hive-quant",
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "alpaca_connected": settings.alpaca_configured,
        "warnings": warnings,
    }


def _collect_mission_control_status(session: Session) -> dict[str, Any]:
    """
    Canonical /api/mission-control/status payload.

    Uses build_mission_control_status (the real exported function — there is
    no build_mission_control_read_model, the prior name was a typo bug).
    """
    try:
        from app.services.mission_control_read_model import build_mission_control_status
        return build_mission_control_status(session)
    except Exception:
        # Fallback to cockpit service
        try:
            from app.services.mission_control_cockpit_service import mission_control_cockpit
            return mission_control_cockpit(session)
        except Exception as exc:
            return {"error": str(exc)[:200]}


def _collect_tradingview_status(session: Session) -> dict[str, Any]:
    try:
        from app.services.tradingview_integration_service import TradingViewIntegrationService
        return TradingViewIntegrationService(session).status()
    except Exception as exc:
        return {"error": str(exc)[:200], "service": "tradingview"}


def _collect_tradingview_chart(session: Session) -> dict[str, Any]:
    try:
        from app.services.tradingview_integration_service import TradingViewIntegrationService
        return TradingViewIntegrationService(session).chart(
            symbol="BTC/USD", timeframe="5Min", limit=120
        )
    except Exception as exc:
        return {"error": str(exc)[:200], "symbol": "BTC/USD", "timeframe": "5Min"}


def _collect_research_status(session: Session) -> dict[str, Any]:
    try:
        from app.services.research_status_service import research_status
        return research_status(session)
    except Exception:
        try:
            from app.services.research_lab_service import ResearchLabService
            return ResearchLabService(session).status()
        except Exception as exc:
            return {"error": str(exc)[:200], "service": "research"}


def _collect_live_flags_status(session: Session) -> dict[str, Any]:
    try:
        from app.services.live_flags_service import LiveFlagsService
        return LiveFlagsService(session).status()
    except Exception as exc:
        return {"error": str(exc)[:200], "service": "live_flags"}


def _collect_diagnostic_export_status(session: Session) -> dict[str, Any]:
    try:
        from app.services.diagnostic_export_job_service import export_job_status
        return export_job_status(session)
    except Exception as exc:
        return {"error": str(exc)[:200], "service": "diagnostic_export_status"}


def _collect_universe_status(session: Session) -> dict[str, Any]:
    try:
        from app.services.universe_service import universe_status
        st = universe_status(session)
        # Add a small ranking sample if available — non-essential, best effort
        try:
            from app.services.universe_sources_service import universe_scan_summary
            st["scan_summary"] = universe_scan_summary(session)
        except Exception:
            pass
        return st
    except Exception as exc:
        return {"error": str(exc)[:200], "service": "universe_status"}


def _collect_paper_execution_status(session: Session) -> dict[str, Any]:
    try:
        from app.services.paper_execution_service import PaperExecutionService
        return PaperExecutionService(session).status()
    except Exception as exc:
        return {"error": str(exc)[:200], "service": "paper_execution_status"}


def _collect_cockpit(session: Session) -> dict[str, Any]:
    try:
        from app.services.mission_control_cockpit_service import mission_control_cockpit
        return mission_control_cockpit(session)
    except Exception as exc:
        return {"error": str(exc)[:200], "service": "cockpit"}


def _collect_portfolio_status(session: Session) -> dict[str, Any]:
    """Broker-truth-first portfolio summary (read-only)."""
    try:
        from app.services.portfolio_truth_service import portfolio_truth_snapshot
        return portfolio_truth_snapshot(session)
    except Exception:
        try:
            from app.services.broker_reconciliation_service import BrokerReconciliationService
            return BrokerReconciliationService(session).broker_position_availability_audit()
        except Exception as exc:
            return {"error": str(exc)[:200], "service": "portfolio"}


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

# Order matters for the manifest list — kept stable for diffing across runs.
ENDPOINTS_SAFE: list[tuple[str, str, Callable[[Session], Any]]] = [
    ("/api/health", "health.json", lambda s: _collect_health()),
    ("/api/mission-control/status", "mission_control_status.json", _collect_mission_control_status),
    ("/api/tradingview/status", "tradingview_status.json", _collect_tradingview_status),
    ("/api/tradingview/chart?symbol=BTC/USD&timeframe=5Min&limit=120", "tradingview_chart_btcusd_5min.json", _collect_tradingview_chart),
    ("/api/research/status", "research_status.json", _collect_research_status),
    ("/api/live-flags/status", "live_flags_status.json", _collect_live_flags_status),
    ("/api/diagnostics/export/status", "diagnostic_export_status.json", _collect_diagnostic_export_status),
    ("/api/universe/status", "universe_status.json", _collect_universe_status),
    ("/api/execution/paper/status", "paper_execution_status.json", _collect_paper_execution_status),
    ("/api/cockpit", "cockpit.json", _collect_cockpit),
    ("/api/portfolio/status", "portfolio_status.json", _collect_portfolio_status),
]


def collect_api_snapshots(session: Session) -> dict[str, Any]:
    """
    Build the api_snapshots/ folder contents for the bundle.

    Returns dict {"api_snapshots/<file>.json": <envelope>, ...} plus a
    manifest at "api_snapshots/_manifest.json".
    """
    out: dict[str, Any] = {}
    manifest_entries: list[dict[str, Any]] = []
    for endpoint, filename, fn in ENDPOINTS_SAFE:
        snap = _safe_call(endpoint, lambda fn=fn: fn(session))
        key = f"{_API_SNAPSHOT_DIR}/{filename}"
        out[key] = snap
        manifest_entries.append({
            "endpoint": endpoint,
            "file": key,
            "status_code": snap.get("status_code"),
            "error": snap.get("error"),
            "elapsed_ms": snap.get("elapsed_ms"),
        })

    out[f"{_API_SNAPSHOT_DIR}/_manifest.json"] = {
        "schema_version": 1,
        "captured_at_utc": datetime.utcnow().isoformat() + "Z",
        "snapshot_count": len(ENDPOINTS_SAFE),
        "successes": sum(1 for e in manifest_entries if not e["error"]),
        "failures": sum(1 for e in manifest_entries if e["error"]),
        "entries": manifest_entries,
        "rules": [
            "read_only=true",
            "no_POST",
            "no_mutation",
            "no_cycle_run",
            "no_provider_fetch_loop",
            "no_order_submission",
            "no_gemini_call",
        ],
    }
    return out
