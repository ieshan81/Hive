"""Pre-submit validation for Alpaca crypto paper orders (docs-aligned)."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import ExecutionLog, OrderRecord
from app.services.alpaca_adapter import AlpacaAdapter, normalize_crypto_symbol
from app.services.alpaca_crypto_assets import fetch_crypto_assets, get_crypto_asset
from app.services.alpaca_precision import normalize_order_fields
from app.services.engine_config import cfg_get


CRYPTO_ORDER_TYPES = frozenset({"market", "limit", "stop_limit"})
CRYPTO_TIF = frozenset({"gtc", "ioc"})
FUNDED_QUOTES = frozenset({"USD", "USDT", "USDC", "BTC"})
MAX_CRYPTO_NOTIONAL_DEFAULT = 200_000.0


@dataclass
class CryptoOrderValidation:
    valid: bool
    validator_reasons: list[str] = field(default_factory=list)
    reject_code: Optional[str] = None
    normalized_payload: dict[str, Any] = field(default_factory=dict)
    asset_metadata: dict[str, Any] = field(default_factory=dict)
    buying_power_check: dict[str, Any] = field(default_factory=dict)
    quote_currency_check: dict[str, Any] = field(default_factory=dict)
    precision_adjustments: dict[str, Any] = field(default_factory=dict)
    would_submit_to_broker: bool = False


def _round_down(value: float, increment: float) -> float:
    if increment is None or increment <= 0:
        return value
    steps = math.floor(value / increment + 1e-12)
    return round(steps * increment, 12)


def _round_price(value: float, increment: float) -> float:
    if increment is None or increment <= 0:
        return round(value, 8)
    steps = round(value / increment)
    return round(steps * increment, 12)


class AlpacaCryptoOrderValidator:
    def __init__(self, session: Session, alpaca: AlpacaAdapter, config: dict):
        self.session = session
        self.alpaca = alpaca
        self.config = config

    def validate_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str = "limit",
        time_in_force: str = "ioc",
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        limit_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        account=None,
        open_order_symbols: Optional[set[str]] = None,
        allow_duplicate_symbol: bool = False,
        dry_run: bool = True,
    ) -> CryptoOrderValidation:
        reasons: list[str] = []
        sym = normalize_crypto_symbol(symbol)
        otype = (order_type or "limit").lower().replace("-", "_")
        tif = (time_in_force or "ioc").lower()

        assets = fetch_crypto_assets()
        meta = get_crypto_asset(sym) or assets.get(sym)
        if not meta:
            reasons.append(f"Unknown crypto symbol {sym} — not in Alpaca asset list")
            return CryptoOrderValidation(
                valid=False,
                validator_reasons=reasons,
                reject_code="CRYPTO_ASSET_UNKNOWN",
            )

        if not meta.get("tradable") or meta.get("status") != "active":
            reasons.append(f"{sym} not tradable or not active (status={meta.get('status')})")
            return CryptoOrderValidation(
                valid=False,
                validator_reasons=reasons,
                reject_code="CRYPTO_NOT_TRADABLE",
                asset_metadata=meta,
            )

        quote_ccy = meta.get("quote_currency") or "USD"
        qc = {"quote_currency": quote_ccy, "funded": quote_ccy in FUNDED_QUOTES}
        if not qc["funded"]:
            reasons.append(f"Quote currency {quote_ccy} not in funded set {sorted(FUNDED_QUOTES)}")

        if otype not in CRYPTO_ORDER_TYPES:
            reasons.append(f"Order type {otype} not supported for crypto (market, limit, stop_limit)")
        if tif not in CRYPTO_TIF:
            reasons.append(f"time_in_force {tif} invalid — crypto allows gtc or ioc only")
        if otype == "market" and tif not in ("gtc", "ioc"):
            reasons.append("Market crypto orders require gtc or ioc")

        if qty is not None and notional is not None:
            reasons.append("Cannot send both qty and notional in one order")

        min_sz = float(meta.get("min_order_size") or 0)
        inc = float(meta.get("min_trade_increment") or 0) or min_sz or 1e-8
        price_inc = float(meta.get("price_increment") or 0) or 1e-8

        adj: dict[str, Any] = {}
        norm_qty = qty
        norm_notional = notional
        norm_limit = limit_price

        if norm_qty is not None:
            px_meta = normalize_order_fields(qty=float(norm_qty), min_trade_increment=inc)
            norm_qty = px_meta.get("normalized_qty", norm_qty)
            adj.update({k: v for k, v in px_meta.items() if k != "normalized_qty"})
            if px_meta.get("raw_qty") != norm_qty:
                adj["qty_quantized"] = px_meta

        if norm_limit is not None:
            lp_meta = normalize_order_fields(limit_price=float(norm_limit), price_increment=price_inc)
            norm_limit = lp_meta.get("normalized_limit_price", norm_limit)
            adj.update({k: v for k, v in lp_meta.items() if k != "normalized_limit_price"})
            if lp_meta.get("raw_limit_price") != norm_limit:
                adj["limit_price_quantized"] = lp_meta

        if norm_qty is not None and min_sz and norm_qty < min_sz:
            reasons.append(f"qty {norm_qty} below min_order_size {min_sz}")

        alpaca_min_notional = float(
            cfg_get(self.config, "execution.alpaca_crypto_min_notional_usd", 10.0)
        )
        max_notional = float(
            cfg_get(self.config, "execution.crypto_max_notional_usd", MAX_CRYPTO_NOTIONAL_DEFAULT)
        )
        est_notional = norm_notional
        if est_notional is None and norm_qty and norm_limit:
            est_notional = norm_qty * norm_limit
        elif est_notional is None and norm_qty and limit_price:
            est_notional = norm_qty * float(limit_price)

        bp_check: dict[str, Any] = {}
        if account and est_notional and side.lower() == "buy":
            raw = getattr(account, "raw_payload", None) or {}
            nmbp = raw.get("non_marginable_buying_power")
            buying = float(nmbp if nmbp is not None else account.buying_power or 0)
            buffer_pct = float(cfg_get(self.config, "execution.buying_power_buffer_pct", 2.0))
            need = est_notional * (1 + buffer_pct / 100.0)
            bp_check = {
                "non_marginable_buying_power": buying,
                "required_with_buffer": round(need, 4),
                "est_notional": round(est_notional, 4),
                "passed": buying >= need,
            }
            if not bp_check["passed"]:
                reasons.append(
                    f"non_marginable_buying_power {buying:.2f} < required {need:.2f} (notional + buffer)"
                )

        if est_notional and est_notional < alpaca_min_notional:
            reasons.append(
                f"notional ${est_notional:.2f} below Alpaca crypto minimum ${alpaca_min_notional:.2f} "
                f"(cost basis must be >= minimal amount of order)"
            )
        if est_notional and est_notional > max_notional:
            reasons.append(f"notional {est_notional:.2f} exceeds max {max_notional:.2f}")

        if client_order_id:
            dup = self.session.exec(
                select(OrderRecord).where(OrderRecord.broker_client_order_id == client_order_id)
            ).first()
            if dup:
                reasons.append(f"client_order_id {client_order_id} already used")

        if not allow_duplicate_symbol and open_order_symbols and sym in open_order_symbols:
            reasons.append(f"Open order already exists for {sym}")

        if not allow_duplicate_symbol:
            open_log = self.session.exec(
                select(ExecutionLog).where(
                    ExecutionLog.symbol == sym,
                    ExecutionLog.status.in_(
                        ("paper_order_submitted", "paper_order_pending", "paper_order_partially_filled")
                    ),
                )
            ).first()
            if open_log:
                reasons.append(f"Pending/submitted execution log exists for {sym}")

        payload: dict[str, Any] = {
            "symbol": sym,
            "side": side.lower(),
            "type": otype,
            "time_in_force": tif,
        }
        if norm_qty is not None:
            payload["qty"] = norm_qty
        if norm_notional is not None:
            payload["notional"] = round(float(norm_notional), 2)
        if norm_limit is not None and otype in ("limit", "stop_limit"):
            payload["limit_price"] = norm_limit
        if client_order_id:
            payload["client_order_id"] = client_order_id

        valid = len(reasons) == 0
        reject = None
        if reasons:
            reject = reasons[0].split("—")[0].strip()[:64].upper().replace(" ", "_") if reasons else "VALIDATOR_BLOCK"
            if "min_order_size" in reasons[0]:
                reject = "CRYPTO_QTY_BELOW_MIN"
            elif "buying_power" in reasons[0]:
                reject = "CRYPTO_INSUFFICIENT_BUYING_POWER"
            elif "precision" in reasons[0] or "increment" in reasons[0]:
                reject = "CRYPTO_PRECISION_INVALID"

        return CryptoOrderValidation(
            valid=valid,
            validator_reasons=reasons,
            reject_code=reject,
            normalized_payload=payload,
            asset_metadata=meta,
            buying_power_check=bp_check,
            quote_currency_check=qc,
            precision_adjustments=adj,
            would_submit_to_broker=valid and not dry_run,
        )

    def validate_for_candidate(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        limit_price: float,
        client_order_id: str,
        account,
        open_order_symbols: Optional[set[str]] = None,
        recipe: Optional[str] = None,
    ) -> CryptoOrderValidation:
        """Validate limit IOC qty path or market notional path from config recipe."""
        recipe = recipe or str(
            cfg_get(self.config, "execution.crypto_paper_recipe", "limit_ioc_qty")
        )
        if recipe == "market_notional":
            mid = limit_price
            notional = qty * mid if mid > 0 else None
            return self.validate_order(
                symbol=symbol,
                side=side,
                order_type="market",
                time_in_force="gtc",
                notional=notional,
                client_order_id=client_order_id,
                account=account,
                open_order_symbols=open_order_symbols,
            )
        return self.validate_order(
            symbol=symbol,
            side=side,
            order_type="limit",
            time_in_force="ioc",
            qty=qty,
            limit_price=limit_price,
            client_order_id=client_order_id,
            account=account,
            open_order_symbols=open_order_symbols,
        )
