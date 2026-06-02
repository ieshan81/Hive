"""Alpaca broker adapter — real paper data only."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import settings
from app.services.broker_safety import is_paper_broker_url
from app.services.broker_submission_guard import blocked_submission_result, guard_before_submit
from app.database import AccountSnapshot, BrokerError, PositionSnapshot

from app.services.cycle_context import current_cycle_run_id
from app.services.quote_utils import normalize_prices, spread_from_bid_ask

logger = logging.getLogger(__name__)

_SYNC_CACHE: dict[str, Any] = {}
_ACCOUNT_CACHE_TTL_SEC = 25
_POSITIONS_CACHE_TTL_SEC = 25
_RATE_LIMIT_BACKOFF_SEC = 90


def _is_rate_limited() -> bool:
    until = _SYNC_CACHE.get("rate_limited_until")
    return bool(until and datetime.utcnow() < until)


def _mark_rate_limited(exc: Exception | str) -> None:
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many" in msg:
        _SYNC_CACHE["rate_limited_until"] = datetime.utcnow() + timedelta(seconds=_RATE_LIMIT_BACKOFF_SEC)


def normalize_crypto_symbol(symbol: str) -> str:
    """Alpaca crypto quotes use BTC/USD; trading assets may be BTCUSD."""
    if "/" in symbol:
        return symbol
    if symbol.endswith("USD") and len(symbol) > 3:
        return f"{symbol[:-3]}/USD"
    return symbol


def configured_stock_feed_name() -> str:
    """Configured stock data feed name (lower-case): 'iex' (default) or 'sip'."""
    return str(getattr(settings, "alpaca_stock_feed", "iex") or "iex").lower()


def stock_data_delay_minutes() -> int:
    """Minutes to hold back the request end-time for stock bars (Basic plan can't query
    the most-recent ~15 min). 0 disables the delay window."""
    try:
        return max(0, int(getattr(settings, "alpaca_stock_data_delay_minutes", 16) or 0))
    except (TypeError, ValueError):
        return 16


def resolve_stock_feed():
    """Map the configured feed name to an alpaca-py DataFeed enum (IEX unless SIP is set)."""
    try:
        from alpaca.data.enums import DataFeed
    except Exception:
        return None
    return {"iex": DataFeed.IEX, "sip": DataFeed.SIP}.get(configured_stock_feed_name(), DataFeed.IEX)


def stock_max_bar_age_minutes() -> int:
    """Max age (minutes) for a stock bar to count as fresh during market hours."""
    try:
        return max(1, int(getattr(settings, "alpaca_stock_max_bar_age_minutes", 30) or 30))
    except (TypeError, ValueError):
        return 30


def stock_max_closed_bar_age_minutes() -> int:
    """Max age (minutes) for a last-session stock bar to count as fresh while the market is closed."""
    try:
        return max(1, int(getattr(settings, "alpaca_stock_max_closed_bar_age_minutes", 5760) or 5760))
    except (TypeError, ValueError):
        return 5760


class AlpacaAdapter:
    def __init__(self, session: Session):
        self.session = session
        self._client = None
        self._data_client = None
        self.broker_sync_rate_limited = _is_rate_limited()
        self.broker_sync_failed = False

    @property
    def configured(self) -> bool:
        return settings.alpaca_configured

    def _guard_submission(self) -> Optional[dict]:
        """Config-aware submission guard (defense-in-depth at the adapter boundary).

        Loads the current config so the guard checks the runtime live flags (not just the paper
        URL + env). FAILS CLOSED if the config/safety context cannot be read — a direct adapter
        submit without proper paper/config context must not proceed."""
        try:
            from app.services.config_manager import ConfigManager

            cfg = ConfigManager(self.session).get_current()
        except Exception:
            return blocked_submission_result("PAPER_PROTECTION_CONTEXT_UNAVAILABLE",
                                             detail="config context unavailable — submission failed closed")
        if cfg is None:
            return blocked_submission_result("NO_CONFIG_CONTEXT", detail="no config context — failed closed")
        return guard_before_submit(cfg)

    def _last_account_snapshot(self) -> Optional[AccountSnapshot]:
        return self.session.exec(select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())).first()

    def sync_account_cached(self, *, force: bool = False) -> Optional[AccountSnapshot]:
        """Return account snapshot bound to this request session — never a detached ORM from global cache."""
        if _is_rate_limited() and not force:
            self.broker_sync_rate_limited = True
            return self._last_account_snapshot()
        cached_at = _SYNC_CACHE.get("account_cached_at")
        if (
            not force
            and cached_at
            and (datetime.utcnow() - cached_at).total_seconds() < _ACCOUNT_CACHE_TTL_SEC
        ):
            return self._last_account_snapshot()
        snap = self.sync_account()
        if snap:
            _SYNC_CACHE["account_cached_at"] = datetime.utcnow()
        return snap or self._last_account_snapshot()

    def sync_positions_cached(self, *, force: bool = False) -> list[PositionSnapshot]:
        if _is_rate_limited() and not force:
            self.broker_sync_rate_limited = True
            return list(self.session.exec(select(PositionSnapshot)).all())
        cached_at = _SYNC_CACHE.get("positions_cached_at")
        if (
            not force
            and cached_at
            and (datetime.utcnow() - cached_at).total_seconds() < _POSITIONS_CACHE_TTL_SEC
        ):
            return list(self.session.exec(select(PositionSnapshot)).all())
        pos = self.sync_positions()
        _SYNC_CACHE["positions_cached_at"] = datetime.utcnow()
        return pos

    def _log_error(self, operation: str, message: str, details: Optional[dict] = None) -> None:
        cycle_id = current_cycle_run_id.get()
        payload = dict(details or {})
        if cycle_id:
            payload.setdefault("cycle_run_id", cycle_id)
        row = BrokerError(
            operation=operation,
            message=message,
            details=payload or None,
            cycle_run_id=cycle_id,
        )
        self.session.add(row)
        try:
            self.session.flush()
        except Exception:
            self.session.rollback()
        logger.error("Alpaca %s: %s", operation, message)

    def _get_trading_client(self):
        if not self.configured:
            return None
        if self._client is None:
            try:
                from alpaca.trading.client import TradingClient

                self._client = TradingClient(
                    settings.alpaca_api_key,
                    settings.alpaca_secret_key,
                    paper=True,
                )
            except Exception as exc:
                self._log_error("init_trading_client", str(exc))
                return None
        return self._client

    def _get_data_client(self):
        if not self.configured:
            return None
        if self._data_client is None:
            try:
                from alpaca.data.historical import StockHistoricalDataClient

                self._data_client = StockHistoricalDataClient(
                    settings.alpaca_api_key,
                    settings.alpaca_secret_key,
                )
            except Exception as exc:
                self._log_error("init_data_client", str(exc))
                return None
        return self._data_client

    def sync_account(self) -> Optional[AccountSnapshot]:
        if _is_rate_limited():
            self.broker_sync_rate_limited = True
            return self._last_account_snapshot()
        client = self._get_trading_client()
        if client is None:
            return self._last_account_snapshot()
        try:
            account = client.get_account()
            equity = float(account.equity)
            last = self.session.exec(
                select(AccountSnapshot).order_by(AccountSnapshot.synced_at.desc())
            ).first()
            peak = equity
            if last and last.equity_peak:
                peak = max(last.equity_peak, equity)
            daily_pl = float(account.equity) - float(account.last_equity) if account.last_equity else 0.0
            last_eq = float(account.last_equity) if account.last_equity else equity
            daily_pl_pct = (daily_pl / last_eq * 100) if last_eq else 0.0
            from app.services import quant_math

            dd = quant_math.drawdown(equity, peak)
            snap = AccountSnapshot(
                equity=equity,
                cash=float(account.cash),
                buying_power=float(account.buying_power),
                portfolio_value=float(account.portfolio_value),
                daily_pl=daily_pl,
                daily_pl_pct=daily_pl_pct,
                drawdown_pct=dd * 100,
                equity_peak=peak,
                raw_payload={
                    "status": str(account.status),
                    "currency": account.currency,
                    "pattern_day_trader": account.pattern_day_trader,
                    "non_marginable_buying_power": float(
                        getattr(account, "non_marginable_buying_power", account.buying_power) or 0
                    ),
                    "buying_power": float(account.buying_power or 0),
                },
            )
            self.session.add(snap)
            self.session.commit()
            self.session.refresh(snap)
            self.broker_sync_rate_limited = False
            return snap
        except Exception as exc:
            _mark_rate_limited(exc)
            self.broker_sync_rate_limited = _is_rate_limited()
            self._log_error("sync_account", str(exc))
            return self._last_account_snapshot()

    def sync_positions(self) -> list[PositionSnapshot]:
        if _is_rate_limited():
            self.broker_sync_rate_limited = True
            return list(self.session.exec(select(PositionSnapshot)).all())
        client = self._get_trading_client()
        if client is None:
            self.broker_sync_failed = True
            prior = list(self.session.exec(select(PositionSnapshot)).all())
            return prior
        try:
            positions = client.get_all_positions()
            staged: list[PositionSnapshot] = []
            for pos in positions:
                staged.append(
                    PositionSnapshot(
                        symbol=pos.symbol,
                        qty=float(pos.qty),
                        side=pos.side.value if hasattr(pos.side, "value") else str(pos.side),
                        avg_entry_price=float(pos.avg_entry_price),
                        current_price=float(pos.current_price),
                        market_value=float(pos.market_value),
                        unrealized_pl=float(pos.unrealized_pl),
                        unrealized_pl_pct=float(pos.unrealized_plpc) * 100,
                    )
                )
            from sqlalchemy import delete

            self.session.exec(delete(PositionSnapshot))
            for snap in staged:
                self.session.add(snap)
            self.session.commit()
            self.broker_sync_rate_limited = False
            self.broker_sync_failed = False
            return staged
        except Exception as exc:
            _mark_rate_limited(exc)
            self.broker_sync_rate_limited = _is_rate_limited()
            self.broker_sync_failed = True
            self._log_error("sync_positions", str(exc))
            self.session.rollback()
            prior = list(self.session.exec(select(PositionSnapshot)).all())
            return prior

    def get_tradable_assets(self, asset_class: str = "stock", limit: int = 500) -> list[dict]:
        client = self._get_trading_client()
        if client is None:
            return []
        try:
            from alpaca.trading.requests import GetAssetsRequest
            from alpaca.trading.enums import AssetStatus, AssetClass

            ac = AssetClass.CRYPTO if asset_class == "crypto" else AssetClass.US_EQUITY
            req = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=ac)
            assets = client.get_all_assets(req)
            tradable = [a for a in assets if a.tradable]
            return [
                {
                    "symbol": a.symbol,
                    "name": a.name,
                    "tradable": a.tradable,
                    "fractionable": a.fractionable,
                    "shortable": a.shortable,
                    "asset_class": asset_class,
                }
                for a in tradable[:limit]
            ]
        except Exception as exc:
            self._log_error("get_tradable_assets", str(exc), {"asset_class": asset_class})
            return []

    def get_crypto_assets(self, limit: int = 20) -> list[dict]:
        return self.get_tradable_assets(asset_class="crypto", limit=limit)

    def get_most_actives(self, limit: int = 15) -> list[dict]:
        if not self.configured:
            return []
        try:
            from alpaca.data.enums import MostActivesBy
            from alpaca.data.historical.screener import ScreenerClient
            from alpaca.data.requests import MostActivesRequest

            screener = ScreenerClient(settings.alpaca_api_key, settings.alpaca_secret_key)
            req = MostActivesRequest(by=MostActivesBy.VOLUME, top=limit)
            actives = screener.get_most_actives(req)
            results = []
            for item in (actives.most_actives or [])[:limit]:
                results.append(
                    {
                        "symbol": item.symbol,
                        "name": item.symbol,
                        "tradable": True,
                        "fractionable": True,
                        "volume": float(item.volume) if hasattr(item, "volume") and item.volume else None,
                    }
                )
            return results
        except Exception as exc:
            self._log_error("get_most_actives", str(exc))
            return self.get_tradable_assets(asset_class="stock", limit=limit)

    @staticmethod
    def compute_spread(bid: float, ask: float) -> tuple[float | None, float | None]:
        spread_pct, _ = spread_from_bid_ask(bid, ask)
        if spread_pct is None:
            return None, None
        return spread_pct, spread_pct * 100

    def get_quote(
        self,
        symbol: str,
        asset_class: str = "stock",
        reference_price: Optional[float] = None,
    ) -> Optional[dict]:
        if asset_class == "crypto":
            return self.get_latest_crypto_quote(symbol, reference_price=reference_price)
        return self.get_latest_quote(symbol, reference_price=reference_price)

    def get_latest_crypto_quote(
        self, symbol: str, reference_price: Optional[float] = None
    ) -> Optional[dict]:
        if not self.configured:
            return None
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoLatestQuoteRequest

            quote_symbol = normalize_crypto_symbol(symbol)
            client = CryptoHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_secret_key)
            req = CryptoLatestQuoteRequest(symbol_or_symbols=quote_symbol)
            quotes = client.get_crypto_latest_quote(req)
            if quote_symbol not in quotes:
                return None
            q = quotes[quote_symbol]
            bid = float(q.bid_price)
            ask = float(q.ask_price)
            bid, ask = normalize_prices(bid, ask, reference_price)
            spread_pct, spread_display = spread_from_bid_ask(bid, ask)
            mid = (bid + ask) / 2.0
            ts = getattr(q, "timestamp", None)
            quote_ts = ts.isoformat() if ts is not None else None
            return {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_pct": spread_pct,
                "spread_display": spread_display,
                "quote_timestamp": quote_ts,
            }
        except Exception as exc:
            self._log_error("get_latest_crypto_quote", str(exc), {"symbol": symbol})
            return None

    def get_crypto_bars(
        self,
        symbol: str,
        timeframe: str = "1Hour",
        limit: int = 50,
        *,
        lookback_days: Optional[int] = None,
    ) -> list[dict]:
        if not self.configured:
            return []
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

            quote_symbol = normalize_crypto_symbol(symbol)
            tf_map = {
                "1Min": TimeFrame(1, TimeFrameUnit.Minute),
                "5Min": TimeFrame(5, TimeFrameUnit.Minute),
                "15Min": TimeFrame(15, TimeFrameUnit.Minute),
                "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
                "1Day": TimeFrame(1, TimeFrameUnit.Day),
            }
            if timeframe not in tf_map:
                self._log_error(
                    "get_crypto_bars",
                    f"unsupported timeframe {timeframe}",
                    {"symbol": symbol},
                )
                return []
            tf = tf_map[timeframe]
            end = datetime.utcnow()
            # Window must end at `now` — with 5Min bars, limit=500 only covers ~41h from `start`.
            if timeframe in ("1Min", "5Min", "15Min"):
                bar_minutes = {"1Min": 1, "5Min": 5, "15Min": 15}[timeframe]
                window_hours = max(6, (limit * bar_minutes) / 60.0 * 1.15)
                if lookback_days:
                    window_hours = min(window_hours, lookback_days * 24)
                start = end - timedelta(hours=window_hours)
            else:
                days = lookback_days if lookback_days else max(3, limit // 24 + 1)
                start = end - timedelta(days=max(days, 1))
            client = CryptoHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_secret_key)
            req = CryptoBarsRequest(symbol_or_symbols=quote_symbol, timeframe=tf, start=start, end=end, limit=limit)
            bars = client.get_crypto_bars(req)
            if quote_symbol not in bars.data:
                return []
            return [
                {
                    "timestamp": b.timestamp.isoformat(),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
                for b in bars.data[quote_symbol]
            ]
        except Exception as exc:
            _mark_rate_limited(exc)
            self.broker_sync_rate_limited = _is_rate_limited()
            self._log_error("get_crypto_bars", str(exc), {"symbol": symbol})
            return []

    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100, asset_class: str = "stock") -> list[dict]:
        if asset_class == "crypto":
            return self.get_crypto_bars(symbol, timeframe=timeframe, limit=limit)
        data_client = self._get_data_client()
        if data_client is None:
            return []
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

            tf_map = {
                "1Min": TimeFrame(1, TimeFrameUnit.Minute),
                "5Min": TimeFrame(5, TimeFrameUnit.Minute),
                "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
                "1Day": TimeFrame(1, TimeFrameUnit.Day),
            }
            tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
            # Basic/free Alpaca plans cannot query recent SIP data: request IEX and hold the
            # end-time back by the delay window, otherwise stock bars come back empty.
            end = datetime.utcnow() - timedelta(minutes=stock_data_delay_minutes())
            start = end - timedelta(days=limit * 2)
            feed = resolve_stock_feed()
            req_kwargs = {"symbol_or_symbols": symbol, "timeframe": tf, "start": start, "end": end, "limit": limit}
            if feed is not None:
                req_kwargs["feed"] = feed
            req = StockBarsRequest(**req_kwargs)
            bars = data_client.get_stock_bars(req)
            if symbol not in bars.data:
                return []
            return [
                {
                    "timestamp": b.timestamp.isoformat(),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
                for b in bars.data[symbol]
            ]
        except Exception as exc:
            self._log_error("get_bars", str(exc), {"symbol": symbol})
            return []

    def get_latest_quote(
        self, symbol: str, reference_price: Optional[float] = None
    ) -> Optional[dict]:
        data_client = self._get_data_client()
        if data_client is None:
            return None
        try:
            from alpaca.data.requests import StockLatestQuoteRequest

            req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = data_client.get_stock_latest_quote(req)
            if symbol not in quotes:
                return None
            q = quotes[symbol]
            bid = float(q.bid_price)
            ask = float(q.ask_price)
            bid, ask = normalize_prices(bid, ask, reference_price)
            spread_pct, spread_display = spread_from_bid_ask(bid, ask)
            mid = (bid + ask) / 2.0
            return {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_pct": spread_pct,
                "spread_display": spread_display,
            }
        except Exception as exc:
            self._log_error("get_latest_quote", str(exc), {"symbol": symbol})
            return None

    def get_order_by_id(self, order_id: str) -> Optional[dict[str, Any]]:
        client = self._get_trading_client()
        if client is None or not order_id:
            return None
        try:
            order = client.get_order_by_id(order_id)
            filled_qty = float(order.filled_qty) if order.filled_qty else 0
            return {
                "id": str(order.id),
                "symbol": str(order.symbol),
                "side": str(order.side),
                "status": str(order.status),
                "qty": float(order.qty) if order.qty else 0,
                "filled_qty": filled_qty,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "limit_price": float(order.limit_price) if order.limit_price else None,
                "client_order_id": str(order.client_order_id) if order.client_order_id else None,
            }
        except Exception as exc:
            self._log_error("get_order_by_id", str(exc), {"order_id": order_id})
            return None

    def get_open_orders(self, limit: int = 50) -> list[dict]:
        client = self._get_trading_client()
        if client is None:
            return []
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=limit)
            orders = client.get_orders(req)
            return [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": str(o.side),
                    "qty": float(o.qty),
                    "status": str(o.status),
                    "client_order_id": str(o.client_order_id) if o.client_order_id else None,
                }
                for o in orders
            ]
        except Exception as exc:
            self._log_error("get_open_orders", str(exc))
            return []

    def _submit_failure(self, operation: str, exc: Exception, request_payload: dict) -> dict[str, Any]:
        from app.services.alpaca_broker_error import parse_alpaca_exception

        parsed = parse_alpaca_exception(exc)
        self._log_error(
            operation,
            parsed.get("alpaca_message") or parsed.get("error_message") or str(exc),
            {
                **request_payload,
                "http_status": parsed.get("http_status"),
                "alpaca_code": parsed.get("alpaca_code"),
                "broker_error_body": parsed.get("response_body"),
            },
        )
        return {
            "success": False,
            "error": parsed.get("alpaca_message") or str(exc),
            "broker_error": parsed,
            "request_payload": request_payload,
        }

    def submit_marketable_limit_ioc(
        self,
        symbol: str,
        qty: float,
        side: str,
        *,
        limit_price: float,
        client_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Marketable limit IOC — default crypto execution policy."""
        blocked = self._guard_submission()
        if blocked:
            return blocked
        client = self._get_trading_client()
        if client is None:
            return {"success": False, "error": "Alpaca not configured"}
        sym = normalize_crypto_symbol(symbol)
        request_payload = {
            "symbol": sym,
            "qty": qty,
            "side": side.lower(),
            "type": "limit",
            "time_in_force": "ioc",
            "limit_price": limit_price,
            "client_order_id": client_order_id,
        }
        try:
            from alpaca.trading.requests import LimitOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            req = LimitOrderRequest(
                symbol=sym,
                qty=qty,
                side=side_enum,
                time_in_force=TimeInForce.IOC,
                limit_price=limit_price,
                client_order_id=client_order_id,
            )
            order = client.submit_order(req)
            return {
                "success": True,
                "order_id": str(order.id),
                "status": str(order.status),
                "symbol": symbol,
                "limit_price": limit_price,
                "qty": qty,
                "tif": "ioc",
                "request_payload": request_payload,
            }
        except Exception as exc:
            return self._submit_failure("submit_marketable_limit_ioc", exc, request_payload)

    def submit_crypto_market_notional(
        self,
        symbol: str,
        notional: float,
        side: str,
        *,
        client_order_id: Optional[str] = None,
        time_in_force: str = "gtc",
    ) -> dict[str, Any]:
        """Crypto market order by notional (USD quote pairs)."""
        blocked = self._guard_submission()
        if blocked:
            return blocked
        client = self._get_trading_client()
        if client is None:
            return {"success": False, "error": "Alpaca not configured"}
        sym = normalize_crypto_symbol(symbol)
        tif = time_in_force.lower()
        request_payload = {
            "symbol": sym,
            "notional": round(float(notional), 2),
            "side": side.lower(),
            "type": "market",
            "time_in_force": tif,
            "client_order_id": client_order_id,
        }
        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            tif_enum = TimeInForce.IOC if tif == "ioc" else TimeInForce.GTC
            side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            req = MarketOrderRequest(
                symbol=sym,
                notional=round(float(notional), 2),
                side=side_enum,
                time_in_force=tif_enum,
                client_order_id=client_order_id,
            )
            order = client.submit_order(req)
            return {
                "success": True,
                "order_id": str(order.id),
                "status": str(order.status),
                "symbol": symbol,
                "notional": notional,
                "tif": tif,
                "request_payload": request_payload,
            }
        except Exception as exc:
            return self._submit_failure("submit_crypto_market_notional", exc, request_payload)

    def submit_paper_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "market",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict[str, Any]:
        blocked = self._guard_submission()
        if blocked:
            return blocked
        client = self._get_trading_client()
        if client is None:
            return {"success": False, "error": "Alpaca not configured"}
        try:
            from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            if order_type == "limit":
                req = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=side_enum,
                    time_in_force=TimeInForce.DAY,
                    limit_price=stop_loss or 0,
                )
            else:
                req = MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=side_enum,
                    time_in_force=TimeInForce.DAY,
                )
            order = client.submit_order(req)
            return {
                "success": True,
                "order_id": str(order.id),
                "status": str(order.status),
                "symbol": symbol,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }
        except Exception as exc:
            self._log_error("submit_paper_order", str(exc), {"symbol": symbol, "side": side})
            return {"success": False, "error": str(exc)}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        blocked = self._guard_submission()
        if blocked:
            return blocked
        client = self._get_trading_client()
        if client is None:
            return {"success": False, "error": "Alpaca not configured"}
        try:
            client.cancel_order_by_id(order_id)
            return {"success": True, "order_id": order_id}
        except Exception as exc:
            self._log_error("cancel_order", str(exc), {"order_id": order_id})
            return {"success": False, "error": str(exc)}

    def get_orders(self, limit: int = 50) -> list[dict]:
        client = self._get_trading_client()
        if client is None:
            return []
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
            orders = client.get_orders(req)
            return [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": str(o.side),
                    "qty": float(o.qty),
                    "status": str(o.status),
                    "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                }
                for o in orders
            ]
        except Exception as exc:
            self._log_error("get_orders", str(exc))
            return []
