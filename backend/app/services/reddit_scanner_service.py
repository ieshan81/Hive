"""Reddit scanner — read-only official API/OAuth or safe public limited mode."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Optional

_TICKER_RE = re.compile(r"\$?([A-Z]{2,10})(?:/USD)?", re.I)
_CRYPTO_HINTS = {"BTC", "ETH", "SOL", "DOGE", "AVAX", "LINK", "HYPE", "RENDER", "ARB", "DOT"}

_DEFAULT_SUBS = [
    "CryptoCurrency",
    "Bitcoin",
    "ethtrader",
    "dogecoin",
    "solana",
    "wallstreetbets",
    "stocks",
    "investing",
    "pennystocks",
    "options",
]

_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}


def _oauth_configured() -> bool:
    return bool(os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))


def _detect_mode() -> str:
    if _oauth_configured():
        return "oauth"
    return "public_limited"


def _token() -> Optional[str]:
    if not _oauth_configured():
        return None
    import base64
    import urllib.parse

    cid = os.environ["REDDIT_CLIENT_ID"]
    secret = os.environ["REDDIT_CLIENT_SECRET"]
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    data = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "device_id": "caged_hive_readonly"}
    ).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": os.environ.get("REDDIT_USER_AGENT", "caged-hive-quant/1.0 (read-only)"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()).get("access_token")
    except Exception:
        return None


def _fetch_subreddit_oauth(sub: str, token: str, *, limit: int = 15) -> list[dict]:
    url = f"https://oauth.reddit.com/r/{sub}/hot?limit={limit}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": os.environ.get("REDDIT_USER_AGENT", "caged-hive-quant/1.0 (read-only)"),
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode())
    return _parse_listing(data, sub)


def _fetch_subreddit_public(sub: str, *, limit: int = 15) -> list[dict]:
    """Public JSON listing — may be blocked by Reddit; fail gracefully."""
    url = f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": os.environ.get("REDDIT_USER_AGENT", "caged-hive-quant/1.0 (read-only)")},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode())
    return _parse_listing(data, sub)


def _parse_listing(data: dict, sub: str) -> list[dict]:
    posts = []
    for child in (data.get("data") or {}).get("children") or []:
        p = child.get("data") or {}
        posts.append(
            {
                "id": p.get("id"),
                "title": (p.get("title") or "")[:300],
                "permalink": f"https://reddit.com{p.get('permalink', '')}",
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
                "created_utc": p.get("created_utc"),
                "subreddit": sub,
            }
        )
    return posts


def _extract_symbols(text: str) -> list[str]:
    found = set()
    for m in _TICKER_RE.findall(text.upper()):
        if m in _CRYPTO_HINTS:
            found.add(f"{m}/USD")
        elif len(m) >= 3:
            found.add(m)
    return sorted(found)


def reddit_status() -> dict[str, Any]:
    mode = _detect_mode()
    latest = _CACHE.get("payload") or {}
    return {
        "status": "ok",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "mode": mode,
        "active": mode in ("oauth", "public_limited") and bool(latest.get("posts")),
        "read_only": True,
        "posting_enabled": False,
        "commenting_enabled": False,
        "voting_enabled": False,
        "editing_enabled": False,
        "model_training": False,
        "no_posting": True,
        "subreddits_monitored": _DEFAULT_SUBS,
        "symbols_detected": list((latest.get("symbol_mentions") or {}).keys())[:20],
        "last_fetch": latest.get("generated_at_utc"),
        "rate_limit_status": "cached" if _CACHE.get("payload") else "not_fetched",
        "errors": latest.get("errors", []),
        "reason": (
            "OAuth read-only scanner."
            if mode == "oauth"
            else (
                "Public limited read-only (no OAuth credentials)."
                if mode == "public_limited"
                else "Inactive — set REDDIT_CLIENT_ID/SECRET or use public mode."
            )
        ),
    }


def refresh_reddit_scan(*, max_subs: int = 6) -> dict[str, Any]:
    global _CACHE
    mode = _detect_mode()
    errors: list[str] = []
    posts: list[dict] = []
    mention_counter: Counter[str] = Counter()
    velocity: dict[str, float] = defaultdict(float)

    token = _token() if mode == "oauth" else None
    if mode == "oauth" and not token:
        mode = "degraded"
        errors.append("oauth_token_failed")

    fetch_fn = _fetch_subreddit_oauth if token else _fetch_subreddit_public
    for sub in _DEFAULT_SUBS[:max_subs]:
        try:
            batch = fetch_fn(sub, token, limit=12) if token else fetch_fn(sub, limit=12)
            posts.extend(batch)
            for p in batch:
                for s in _extract_symbols(p.get("title") or ""):
                    mention_counter[s] += 1
                    velocity[s] += float(p.get("score", 0)) + 0.1 * float(p.get("num_comments", 0))
            time.sleep(1.2 if token else 2.0)
        except Exception as exc:
            errors.append(f"{sub}:{type(exc).__name__}")

    if not posts and mode == "public_limited":
        mode = "degraded" if errors else "inactive"

    hype = [
        {"symbol": s, "mention_count": c, "velocity_score": round(velocity[s], 2)}
        for s, c in mention_counter.most_common(20)
    ]

    payload = {
        "status": "ok" if posts else "degraded",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "mode": mode,
        "posts": posts[:80],
        "symbol_mentions": dict(mention_counter),
        "reddit_symbol_velocity": hype,
        "hype_risk": [h for h in hype if h["velocity_score"] > 50][:10],
        "errors": errors[:10],
        "read_only": True,
    }
    _CACHE = {"at": time.time(), "payload": payload}
    return payload


def reddit_latest() -> dict[str, Any]:
    if _CACHE.get("payload") and time.time() - float(_CACHE.get("at") or 0) < 900:
        return _CACHE["payload"]
    return refresh_reddit_scan()


def reddit_symbol(symbol: str) -> dict[str, Any]:
    latest = reddit_latest()
    sym = symbol.upper().replace("-", "/")
    mentions = latest.get("symbol_mentions") or {}
    count = mentions.get(sym) or mentions.get(sym.split("/")[0]) or 0
    return {
        "status": "ok",
        "symbol": sym,
        "mention_count": count,
        "mode": latest.get("mode"),
        "hype_risk": count > 5,
    }
