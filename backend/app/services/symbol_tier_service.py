"""Symbol tier policy — majors, alts, meme supported, watch-only, blocked."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.engine_config import cfg_get


TIER_MAJOR = "TIER_MAJOR"
TIER_ALT = "TIER_ALT"
TIER_MEME_SUPPORTED = "TIER_MEME_SUPPORTED"
TIER_WATCH = "TIER_WATCH"
TIER_BLOCKED = "TIER_BLOCKED"


class EngineBoundaryBlocked(Exception):
    """Order path blocked for watch-only / unsupported symbol."""

    def __init__(self, symbol: str, tier: str, reason: str):
        self.symbol = symbol
        self.tier = tier
        self.reason = reason
        super().__init__(f"ENGINE_BOUNDARY_BLOCKED: {symbol} tier={tier} — {reason}")


@dataclass
class SymbolTierInfo:
    symbol: str
    tier: str
    trade_eligible: bool
    order_path_allowed: bool
    watch_only_reason: str | None
    broker_supported: bool = True


def _base_asset(symbol: str) -> str:
    s = symbol.upper().replace("/", "").replace("-", "")
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)]
    return s


class SymbolTierService:
    def __init__(self, config: dict, *, broker_supported_symbols: set[str] | None = None):
        self.config = config
        self.broker_supported = broker_supported_symbols or set()
        rules = cfg_get(config, "symbol_tiers.tier_rules", []) or []

        self._rules: list[tuple[str, str]] = []
        if isinstance(rules, list):
            for r in rules:
                if isinstance(r, dict) and r.get("pattern") and r.get("tier"):
                    self._rules.append((str(r["pattern"]).upper(), str(r["tier"])))

    def classify(self, symbol: str) -> SymbolTierInfo:
        base = _base_asset(symbol)
        tier = TIER_ALT
        for pattern, t in self._rules:
            if pattern in base or pattern in symbol.upper():
                tier = t
                break

        broker_ok = True
        if self.broker_supported:
            norm = symbol.upper().replace("-", "/")
            broker_ok = norm in self.broker_supported or base in {s.split("/")[0] for s in self.broker_supported}

        watch_only = tier in (TIER_WATCH, TIER_BLOCKED)
        if tier == TIER_BLOCKED:
            reason = "Symbol tier blocked by policy"
        elif tier == TIER_WATCH:
            reason = "Watch-only attention coin — no execution path"
        elif not broker_ok:
            tier = TIER_BLOCKED
            watch_only = True
            reason = "Not supported by broker"
        else:
            reason = None

        order_allowed = tier in (TIER_MAJOR, TIER_ALT, TIER_MEME_SUPPORTED) and not watch_only
        return SymbolTierInfo(
            symbol=symbol,
            tier=tier,
            trade_eligible=order_allowed,
            order_path_allowed=order_allowed,
            watch_only_reason=reason,
            broker_supported=broker_ok,
        )

    def assert_order_path(self, symbol: str) -> SymbolTierInfo:
        info = self.classify(symbol)
        if not info.order_path_allowed:
            raise EngineBoundaryBlocked(symbol, info.tier, info.watch_only_reason or "not tradable")
        return info

    def slippage_buffer_key(self, tier: str) -> str:
        if tier == TIER_MEME_SUPPORTED:
            return "meme"
        if tier == TIER_MAJOR:
            return "major"
        return "alt"
