"""Parse Alpaca API errors into operator-safe structured payloads."""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def _try_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def parse_alpaca_exception(exc: Exception) -> dict[str, Any]:
    """Extract HTTP status, Alpaca code/message, and safe response body from SDK errors."""
    out: dict[str, Any] = {
        "error_message": str(exc),
        "http_status": None,
        "alpaca_code": None,
        "alpaca_message": None,
        "response_body": None,
    }
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status is not None:
        out["http_status"] = int(status)

    raw = getattr(exc, "message", None) or getattr(exc, "body", None)
    if raw is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            raw = getattr(resp, "text", None) or getattr(resp, "content", None)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, dict):
        out["response_body"] = raw
        out["alpaca_code"] = raw.get("code")
        out["alpaca_message"] = raw.get("message")
        return out

    parsed = _try_json(str(raw)) if raw is not None else None
    if isinstance(parsed, dict):
        out["response_body"] = parsed
        out["alpaca_code"] = parsed.get("code")
        out["alpaca_message"] = parsed.get("message")
        return out

    text = str(raw or exc)
    parsed = _try_json(text)
    if isinstance(parsed, dict):
        out["response_body"] = parsed
        out["alpaca_code"] = parsed.get("code")
        out["alpaca_message"] = parsed.get("message")
        return out

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        inner = _try_json(m.group(0))
        if isinstance(inner, dict):
            out["response_body"] = inner
            out["alpaca_code"] = inner.get("code")
            out["alpaca_message"] = inner.get("message")
            return out

    out["response_body"] = {"raw": text[:2000]} if text else None
    return out


def classify_reject_reason(parsed: dict[str, Any]) -> str:
    """Map Alpaca body to a stable reject_reason code (not generic BROKER_REJECTED)."""
    msg = str(parsed.get("alpaca_message") or parsed.get("error_message") or "").lower()
    body = parsed.get("response_body")
    if isinstance(body, dict):
        msg = f"{msg} {body.get('message', '')}".lower()
    if "insufficient" in msg and ("balance" in msg or "buying" in msg or "non_marginable" in msg):
        return "BROKER_INSUFFICIENT_BALANCE"
    if "notional" in msg or "minimum" in msg or "min order" in msg or "minimal amount of order" in msg:
        return "BROKER_REJECTED_MIN_NOTIONAL"
    if "cost basis" in msg:
        return "BROKER_REJECTED_MIN_NOTIONAL"
    if "qty" in msg and ("increment" in msg or "precision" in msg or "subtick" in msg):
        return "BROKER_QTY_PRECISION"
    if "price" in msg and ("increment" in msg or "precision" in msg or "subtick" in msg):
        return "BROKER_LIMIT_PRICE_PRECISION"
    if "time_in_force" in msg or "time in force" in msg:
        return "BROKER_INVALID_TIME_IN_FORCE"
    if "not tradable" in msg or "asset not" in msg:
        return "BROKER_SYMBOL_NOT_TRADABLE"
    if "both qty and notional" in msg:
        return "BROKER_QTY_AND_NOTIONAL"
    code = parsed.get("alpaca_code")
    if code == 40310000:
        return "BROKER_INSUFFICIENT_BALANCE"
    return "BROKER_REJECTED"


def broker_rejection_detail(
    *,
    parsed: dict[str, Any],
    request_payload: dict[str, Any],
    symbol: str,
    broker_order_id: Optional[str] = None,
) -> dict[str, Any]:
    """Full safe rejection record for logs, proof API, and diagnostics."""
    return {
        "symbol": symbol,
        "submitted_to_broker": True,
        "broker_response_received": True,
        "blocked_before_broker": False,
        "broker_order_id": broker_order_id,
        "http_status": parsed.get("http_status"),
        "alpaca_code": parsed.get("alpaca_code"),
        "alpaca_message": parsed.get("alpaca_message"),
        "broker_error_body": parsed.get("response_body"),
        "request_payload": request_payload,
        "reject_reason": classify_reject_reason(parsed),
        "plain": parsed.get("alpaca_message") or parsed.get("error_message"),
    }
