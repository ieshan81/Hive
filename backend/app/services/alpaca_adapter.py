"""Alpaca broker adapter — real paper data only."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from app.config import settings
from app.services.broker_safety import is_paper_broker_url
from app.database import AccountSnapshot, BrokerError, PositionSnapshot

from app.services.cycle_context import current_cycle_run_id
from app.services.quote_utils import normalize_prices, spread_from_bid_ask

logger = logging.getLogger(__name__)


def normalize_crypto_symbol(symbol: str) -> str:
    """Alpaca crypto quotes use BTC/USD; trading assets may be BTCUSD."""
    if "/" in symbol:
        return symbol
    if symbol.endswith("USD") and len(symbol) > 3:
        return f"{symbol[:-3]}/USD"
    return symbol


class AlpacaAdapter:
    def __init__(self, session: Session):
        self.session = session
        self._client = None
        self._data_client = None

    @property
    def configured(self) -> bool:
        return settings.alpaca_configured

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
        self.session.commit()
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
        client = self._get_trading_client()
        if client is None:
            return None
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
                },
            )
            self.session.add(snap)
            self.session.commit()
            self.session.refresh(snap)
            return snap
        except Exception as exc:
            self._log_error("sync_account", str(exc))
            return None

    def sync_positions(self) -> list[PositionSnapshot]:
        client = self._get_trading_client()
        if client is None:
            return []
        try:
            from sqlalchemy import delete

            positions = client.get_all_positions()
            self.session.exec(delete(PositionSnapshot))
            results = []
            for pos in positions:
                snap = PositionSnapshot(
                    symbol=pos.symbol,
                    qty=float(pos.qty),
                    side=pos.side.value if hasattr(pos.side, "value") else str(pos.side),
                    avg_entry_price=float(pos.avg_entry_price),
                    current_price=float(pos.current_price),
                    market_value=float(pos.market_value),
                    unrealized_pl=float(pos.unrealized_pl),
                    unrealized_pl_pct=float(pos.unrealized_plpc) * 100,
                )
                self.session.add(snap)
                results.append(snap)
            self.session.commit()
            return results
        except Exception as exc:
            self._log_error("sync_positions", str(exc))
            return []

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
            return {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_pct": spread_pct,
                "spread_display": spread_display,
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
                "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
                "1Day": TimeFrame(1, TimeFrameUnit.Day),
            }
            tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Hour))
            end = datetime.utcnow()
            days = lookback_days if lookback_days else max(limit // 24 + 7, limit * 3 // 24)
            start = end - timedelta(days=max(days, 7))
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
            end = datetime.utcnow()
            start = end - timedelta(days=limit * 2)
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end, limit=limit)
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
        if not is_paper_broker_url():
            return {"success": False, "error": "BROKER_NOT_PAPER"}
        client = self._get_trading_client()
        if client is None:
            return {"success": False, "error": "Alpaca not configured"}
        try:
            from alpaca.trading.requests import LimitOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            side_enum = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            req = LimitOrderRequest(
                symbol=normalize_crypto_symbol(symbol),
                qty=qty,
                side=side_enum,
                time_in_force=TimeInForce.IOC,
                limit_price=round(limit_price, 8),
                client_order_id=client_order_id,
            )
            order = client.submit_order(req)
            return {
                "success": True,
                "order_id": str(order.id),
                "status": str(order.status),
                "symbol": symbol,
                "limit_price": limit_price,
                "tif": "ioc",
            }
        except Exception as exc:
            self._log_error(
                "submit_marketable_limit_ioc",
                str(exc),
                {"symbol": symbol, "side": side, "limit_price": limit_price},
            )
            return {"success": False, "error": str(exc)}

    def submit_paper_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "market",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> dict[str, Any]:
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
