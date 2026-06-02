"""Verify stock bars are requested from a supported feed (IEX by default; SIP only if configured).

A Basic/free Alpaca plan cannot query SIP — omitting the feed (the old behaviour) returned 0 bars.
This asserts the adapter resolves a feed and passes it to StockBarsRequest, defaulting to IEX.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")  # DB-free import
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    src = (BACKEND / "app/services/alpaca_adapter.py").read_text(encoding="utf-8", errors="ignore")
    cfg = (BACKEND / "app/config.py").read_text(encoding="utf-8", errors="ignore")

    # config default must be a supported feed, defaulting to iex
    assert 'alpaca_stock_feed: str = "iex"' in cfg, "config default stock feed is not iex"

    # adapter must resolve + pass a feed to the stock bars request (not omit it)
    assert "def resolve_stock_feed" in src, "resolve_stock_feed helper missing"
    assert "StockBarsRequest(**req_kwargs)" in src and 'req_kwargs["feed"] = feed' in src, \
        "get_bars does not pass a feed to StockBarsRequest"

    from app.services.alpaca_adapter import configured_stock_feed_name, resolve_stock_feed

    feed_name = configured_stock_feed_name()
    assert feed_name in ("iex", "sip"), f"unsupported configured stock feed: {feed_name}"
    # resolve_stock_feed returns a DataFeed enum when alpaca-py is present, else None (guarded).
    resolved = resolve_stock_feed()
    if resolved is not None:
        assert "IEX" in str(resolved).upper() or "SIP" in str(resolved).upper(), f"bad feed enum: {resolved}"
    print(f"verify_stock_data_feed_uses_iex_or_supported_feed: PASS (feed={feed_name}, resolved={resolved})")


if __name__ == "__main__":
    main()
