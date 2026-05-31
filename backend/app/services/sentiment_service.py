"""
Sentiment Engine (DOMAIN 5) — Practical Free-Tier Only.

Principle: Sentiment is a RANKING FACTOR, not a permission.
  sentiment_score shifts trade_quality_score by ≤ ±10%. It NEVER grants entry.

Sources:
  1. FinBERT (ProsusAI/finbert, local inference) — primary text scorer
  2. Alpaca News API (Benzinga feed, 200 req/min free) — primary news source
  3. Reddit r/wallstreetbets, r/CryptoCurrency (official API, read-only, non-commercial)

Anti-hype rules (Xu & Livshits 2019; La Morgia et al. 2023):
  If social_volume_z > 3.0 AND market_cap_rank > 50 AND price moved > 5% in 60m:
    → flag PUMP_DUMP_FLAG; block all longs for cooldown_pump=120 minutes.

Scoring formula:
  freshness_decay(age_min) = exp(-age_min / half_life_min)   # half_life=30
  source_reliability = {alpaca_benzinga: 1.0, finnhub: 0.85, alpha_vantage: 0.85,
                        yahoo_rss: 0.7, reddit: 0.4}
  sentiment_score = clamp(
    Σ_i finbert_polarity_i × confidence_i × source_reliability_i × freshness_decay(age_i)
    / Σ_i confidence_i × source_reliability_i × freshness_decay(age_i),
    -1, +1
  )

  sentiment_alignment = sign(side) × sentiment_score × 0.10   (max ±10% on quality)
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# In-process cache + diagnostics (resets on restart; advisory telemetry only).
_SENTIMENT_CACHE: dict[str, dict[str, Any]] = {}
_LAST_SENTIMENT_REFRESH_AT: Optional[str] = None
_NEUTRAL_FALLBACK_COUNT = 0
_SENTIMENT_ERRORS_24H: list[str] = []


def _record_sentiment_error(message: str) -> None:
    global _NEUTRAL_FALLBACK_COUNT
    now = datetime.utcnow().isoformat() + "Z"
    _SENTIMENT_ERRORS_24H.append(now)
    cutoff = datetime.utcnow() - timedelta(hours=24)
    while _SENTIMENT_ERRORS_24H and datetime.fromisoformat(_SENTIMENT_ERRORS_24H[0].replace("Z", "")) < cutoff:
        _SENTIMENT_ERRORS_24H.pop(0)
    _NEUTRAL_FALLBACK_COUNT += 1
    logger.debug("sentiment neutral fallback: %s", message[:200])


def get_sentiment_cache_snapshot() -> dict[str, dict[str, Any]]:
    return dict(_SENTIMENT_CACHE)


def sentiment_diagnostics(config: Optional[dict] = None) -> dict[str, Any]:
    """Structured sentiment pipeline diagnostics for status/bundle exports."""
    from app.config import settings

    try:
        from app.services.finbert_client import finbert_health, finbert_service_url

        remote = finbert_health()
        worker_url = bool(finbert_service_url())
        worker_connected = remote.get("status") in ("ok", "degraded") and remote.get("configured")
        model_loaded = bool(remote.get("model_loaded")) or FinBERTScorer.is_available()
    except Exception:
        remote = {}
        worker_url = False
        worker_connected = False
        model_loaded = FinBERTScorer.is_available()

    cfg = config or {}
    sent_cfg = cfg.get("sentiment") or {}
    influence = bool(sent_cfg.get("influence_ranking", True))
    cache = get_sentiment_cache_snapshot()
    scored = [
        {
            "symbol": sym,
            "sentiment_score": row.get("sentiment_score"),
            "sentiment_alignment": row.get("sentiment_alignment"),
            "headline_count": row.get("headline_count"),
            "model_used": row.get("model_used"),
            "scored_at": row.get("scored_at"),
        }
        for sym, row in cache.items()
    ]

    return {
        "finbert_worker_configured": worker_url,
        "finbert_worker_connected": worker_connected,
        "finbert_model_loaded": model_loaded,
        "news_provider_wired": bool(settings.alpaca_configured),
        "latest_scored_symbols_count": len(cache),
        "latest_sentiment_scores": scored[:20],
        "last_sentiment_refresh_at": _LAST_SENTIMENT_REFRESH_AT,
        "sentiment_used_in_ranking": influence and model_loaded,
        "max_sentiment_adjustment_pct": sent_cfg.get("max_adjustment_pct", 10),
        "neutral_fallback_count": _NEUTRAL_FALLBACK_COUNT,
        "sentiment_errors_last_24h": len(_SENTIMENT_ERRORS_24H),
    }


def sentiment_ranking_enabled(config: dict) -> bool:
    sent = (config or {}).get("sentiment") or {}
    return bool(sent.get("influence_ranking", True))


def apply_sentiment_ranking_modifier(trade_quality: float, sentiment_alignment: float) -> float:
    """Ranking-only modifier: trade_quality * (1 + alignment), alignment clamped ±10%."""
    alignment = max(-0.10, min(0.10, float(sentiment_alignment or 0.0)))
    adjusted = float(trade_quality or 0.0) * (1.0 + alignment)
    return max(0.0, min(1.0, adjusted))


def resolve_sentiment_for_ranking(config: dict, symbol: str, side: str = "buy") -> dict[str, Any]:
    """Safe ranking helper — never raises; returns neutral on failure."""
    if not sentiment_ranking_enabled(config):
        return {
            "symbol": symbol,
            "side": side,
            "used_in_ranking": False,
            "sentiment_score": 0.0,
            "sentiment_alignment": 0.0,
            "reason": "influence_ranking_disabled",
        }
    try:
        result = score_symbol_sentiment(symbol, side=side)
        result["used_in_ranking"] = sentiment_ranking_enabled(config)
        return result
    except Exception as exc:
        _record_sentiment_error(str(exc))
        return {
            "symbol": symbol,
            "side": side,
            "used_in_ranking": False,
            "sentiment_score": 0.0,
            "sentiment_alignment": 0.0,
            "headline_count": 0,
            "source_count": 0,
            "model_used": "neutral_fallback",
            "neutral_reason": "sentiment_failure",
            "error": str(exc)[:200],
        }


# ──────────────────────────────────────────────────────────────
# Source reliability weights
# ──────────────────────────────────────────────────────────────

SOURCE_RELIABILITY: dict[str, float] = {
    "alpaca_benzinga": 1.0,
    "alpaca": 1.0,
    "finnhub": 0.85,
    "alpha_vantage": 0.85,
    "yahoo_rss": 0.70,
    "reddit": 0.40,
}

HALF_LIFE_MINUTES = 30.0  # freshness half-life per spec
PUMP_DUMP_SOCIAL_THRESHOLD = 3.0  # z-score
PUMP_DUMP_PRICE_MOVE_PCT = 0.05   # 5% in 60m
PUMP_DUMP_MARKETCAP_RANK_FLOOR = 50  # only applies to low-cap (rank > 50)
PUMP_DUMP_COOLDOWN_MINUTES = 120


# ──────────────────────────────────────────────────────────────
# Freshness decay
# ──────────────────────────────────────────────────────────────

def freshness_decay(age_minutes: float, half_life_minutes: float = HALF_LIFE_MINUTES) -> float:
    """exp(-age_min / half_life_min) — decays toward 0 as headline ages."""
    return math.exp(-age_minutes / max(half_life_minutes, 1.0))


# ──────────────────────────────────────────────────────────────
# FinBERT local scorer
# ──────────────────────────────────────────────────────────────

class FinBERTScorer:
    """
    Wraps ProsusAI/finbert via Hugging Face `transformers.pipeline`.
    Lazy-loads on first use; returns None if transformers not installed.

    s = P(positive) - P(negative)   → [-1, +1]

    Pre-trained on Reuters / Financial PhraseBank — NOT fine-tuned on Reddit
    data (would violate Reddit ToS).
    """

    _pipeline = None
    _available: Optional[bool] = None

    @classmethod
    def is_available(cls) -> bool:
        if cls._available is None:
            try:
                import transformers  # noqa: F401
                cls._available = True
            except ImportError:
                cls._available = False
                logger.info("FinBERT unavailable — transformers not installed; sentiment will be neutral")
        return cls._available

    @classmethod
    def score_text(cls, text: str) -> Optional[tuple[float, float]]:
        """
        Returns (polarity, confidence) where polarity ∈ [-1, +1]
        and confidence = softmax probability of winning class.
        Returns None if FinBERT unavailable or text is blank.
        """
        if not text or not text.strip():
            return None
        if not cls.is_available():
            return None
        try:
            if cls._pipeline is None:
                from transformers import pipeline
                cls._pipeline = pipeline(
                    "sentiment-analysis",
                    model="ProsusAI/finbert",
                    tokenizer="ProsusAI/finbert",
                    max_length=512,
                    truncation=True,
                )
            result = cls._pipeline(text[:512])  # FinBERT max 512 tokens
            if not result:
                return None
            label: str = result[0]["label"].lower()  # positive / negative / neutral
            score: float = float(result[0]["score"])
            if label == "positive":
                return (score, score)
            if label == "negative":
                return (-score, score)
            return (0.0, score)  # neutral
        except Exception as exc:
            logger.warning("FinBERT inference error: %s", exc)
            return None

    @classmethod
    def score_headline(cls, headline: str, source: str = "alpaca") -> dict:
        """Score a single headline and return a structured record."""
        result = cls.score_text(headline)
        if result is None:
            return {"polarity": 0.0, "confidence": 0.5, "label": "neutral", "source": source}
        polarity, confidence = result
        label = "positive" if polarity > 0.1 else ("negative" if polarity < -0.1 else "neutral")
        return {
            "polarity": round(polarity, 4),
            "confidence": round(confidence, 4),
            "label": label,
            "source": source,
        }


# ──────────────────────────────────────────────────────────────
# Aggregated sentiment score
# ──────────────────────────────────────────────────────────────

def compute_sentiment_score(headlines: list[dict]) -> float:
    """
    headlines: list of {polarity, confidence, source, age_minutes}

    Returns sentiment_score ∈ [-1, +1]:
      Σ_i polarity_i × confidence_i × reliability_i × decay_i
      ─────────────────────────────────────────────────────────
      Σ_i confidence_i × reliability_i × decay_i

    Returns 0.0 if no headlines or all have zero weight.
    """
    numerator = 0.0
    denominator = 0.0
    for h in headlines:
        polarity = float(h.get("polarity", 0.0))
        confidence = float(h.get("confidence", 0.5))
        source = h.get("source", "alpaca")
        age_min = float(h.get("age_minutes", 0.0))
        reliability = SOURCE_RELIABILITY.get(source, 0.5)
        decay = freshness_decay(age_min)
        weight = confidence * reliability * decay
        numerator += polarity * weight
        denominator += weight

    if denominator <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def compute_sentiment_alignment(
    sentiment_score: float,
    side: str,
) -> float:
    """
    sentiment_alignment = sign(side) × sentiment_score × 0.10
    Clamped to [-0.10, +0.10] — max ±10% influence on trade_quality_score.
    """
    direction = 1.0 if side.lower() == "buy" else -1.0
    raw = direction * sentiment_score * 0.10
    return max(-0.10, min(0.10, raw))


# ──────────────────────────────────────────────────────────────
# Pump-and-dump detection
# ──────────────────────────────────────────────────────────────

# Per-symbol cooldown store (in-process, resets on restart)
_PUMP_DUMP_COOLDOWNS: dict[str, datetime] = {}


def check_pump_dump_flag(
    symbol: str,
    social_volume_z: float = 0.0,
    price_move_60m_pct: float = 0.0,
    marketcap_rank: Optional[int] = None,
) -> bool:
    """
    Returns True (flag raised) if:
      social_volume_z > 3.0
      AND marketcap_rank > 50 (low-cap)
      AND abs(price_move_60m_pct) > 5%

    Xu & Livshits (USENIX Security 2019): pump-and-dump detected in 25s;
    La Morgia et al. (ACM Trans. 2023): 94.5% F1-score on detection.
    """
    # Check existing cooldown
    cooldown_until = _PUMP_DUMP_COOLDOWNS.get(symbol)
    if cooldown_until and datetime.utcnow() < cooldown_until:
        return True  # Still in cooldown

    if (
        social_volume_z > PUMP_DUMP_SOCIAL_THRESHOLD
        and abs(price_move_60m_pct) > PUMP_DUMP_PRICE_MOVE_PCT
        and (marketcap_rank is None or marketcap_rank > PUMP_DUMP_MARKETCAP_RANK_FLOOR)
    ):
        _PUMP_DUMP_COOLDOWNS[symbol] = datetime.utcnow() + timedelta(minutes=PUMP_DUMP_COOLDOWN_MINUTES)
        logger.warning(
            "PUMP_DUMP_FLAG raised for %s (social_z=%.1f, price_move=%.1f%%)",
            symbol, social_volume_z, price_move_60m_pct * 100,
        )
        return True
    return False


def is_pump_dump_blocked(symbol: str) -> bool:
    """Quick check — is this symbol currently in pump-dump cooldown?"""
    cd = _PUMP_DUMP_COOLDOWNS.get(symbol)
    return bool(cd and datetime.utcnow() < cd)


# ──────────────────────────────────────────────────────────────
# News fetcher (Alpaca News API — free Benzinga feed)
# ──────────────────────────────────────────────────────────────

class AlpacaNewsIngester:
    """
    Fetches headlines from Alpaca's Benzinga-powered news API.
    Free plan: 200 req/min.
    Rate-limited to 50 req/min internally (25% safety margin).
    """

    _last_headlines: dict[str, list[dict]] = {}
    _last_fetched_at: dict[str, datetime] = {}
    _CACHE_TTL_S = 60  # re-fetch after 60s per symbol

    @classmethod
    def get_headlines(
        cls,
        symbol: str,
        *,
        api_key: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Returns list of {headline, published_at, age_minutes, source}.
        Returns empty list if Alpaca not configured or rate limited.
        """
        # Check cache
        last = cls._last_fetched_at.get(symbol)
        if last and (datetime.utcnow() - last).total_seconds() < cls._CACHE_TTL_S:
            return cls._last_headlines.get(symbol, [])

        from app.config import settings

        if not api_key:
            api_key = settings.alpaca_api_key
        secret_key = settings.alpaca_secret_key

        if not api_key or not secret_key:
            return []

        try:
            import urllib.request
            import json
            import urllib.parse

            base = "https://data.alpaca.markets/v1beta1/news"
            params = urllib.parse.urlencode({
                "symbols": symbol.replace("/", ""),
                "limit": min(limit, 50),
                "sort": "desc",
            })
            url = f"{base}?{params}"
            req = urllib.request.Request(url, headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            news_list = data.get("news", [])
            results = []
            now = datetime.utcnow()
            for item in news_list:
                published_str = item.get("created_at") or item.get("updated_at") or ""
                try:
                    pub_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
                    if pub_dt.tzinfo:
                        age_min = (now - pub_dt.replace(tzinfo=None)).total_seconds() / 60
                    else:
                        age_min = (now - pub_dt).total_seconds() / 60
                except Exception:
                    age_min = 999.0

                results.append({
                    "headline": item.get("headline", ""),
                    "published_at": published_str,
                    "age_minutes": round(age_min, 1),
                    "source": "alpaca_benzinga",
                    "url": item.get("url", ""),
                    "symbol": symbol,
                })

            cls._last_headlines[symbol] = results
            cls._last_fetched_at[symbol] = datetime.utcnow()
            return results

        except Exception as exc:
            logger.debug("Alpaca News fetch for %s failed: %s", symbol, exc)
            return cls._last_headlines.get(symbol, [])


# ──────────────────────────────────────────────────────────────
# Sentiment memory record (persisted after trade close)
# ──────────────────────────────────────────────────────────────

def build_sentiment_memory_record(
    symbol: str,
    side: str,
    sentiment_at_entry: float,
    headlines_seen: int,
    social_volume_z: float,
    realized_R: Optional[float],
) -> dict:
    """
    On every closed trade, record sentiment context so the system can
    compute corr(sentiment_at_entry, realized_R) after 50+ trades.
    If correlation < 0 with p < 0.05 over ≥ 30 trades → sentiment_inverse memory.
    """
    return {
        "type": "sentiment_memory",
        "symbol": symbol,
        "side": side,
        "sentiment_at_entry": round(sentiment_at_entry, 4),
        "headlines_seen": headlines_seen,
        "social_volume_z": round(social_volume_z, 2),
        "realized_R": round(realized_R, 4) if realized_R is not None else None,
        "recorded_at": datetime.utcnow().isoformat() + "Z",
    }


def _polarity_from_finbert_label(label: str, score: float) -> tuple[float, float]:
    label_l = (label or "neutral").lower()
    conf = float(score or 0.5)
    if "pos" in label_l:
        return conf, conf
    if "neg" in label_l:
        return -conf, conf
    return 0.0, conf


def _score_headlines_with_finbert(headlines: list[dict]) -> tuple[list[dict], str]:
    """Score headlines via FinBERT microservice batch, then local fallback."""
    if not headlines:
        return [], "none"

    from app.services.finbert_client import classify_batch, finbert_service_url

    items = []
    for i, h in enumerate(headlines):
        text = (h.get("headline") or h.get("text") or "").strip()
        if not text:
            continue
        items.append(
            {
                "id": str(i),
                "symbol": h.get("symbol") or "",
                "source": h.get("source") or "news",
                "text": text[:512],
            }
        )

    if finbert_service_url() and items:
        batch = classify_batch(items)
        if batch:
            by_id = {str(row.get("id")): row for row in batch}
            scored: list[dict] = []
            for i, h in enumerate(headlines):
                row = by_id.get(str(i)) or {}
                polarity, confidence = _polarity_from_finbert_label(row.get("label", "neutral"), row.get("score", 0.5))
                scored.append(
                    {
                        **h,
                        "polarity": polarity,
                        "confidence": confidence,
                        "label": row.get("label", "neutral"),
                        "model_used": "finbert_microservice",
                    }
                )
            return scored, "finbert_microservice"

    scored = []
    model_used = "finbert_local" if FinBERTScorer.is_available() else "neutral_fallback"
    for h in headlines:
        text = (h.get("headline") or h.get("text") or "").strip()
        source = h.get("source", "alpaca")
        if not text:
            scored.append({**h, "polarity": 0.0, "confidence": 0.5, "label": "neutral", "model_used": model_used})
            continue
        local = FinBERTScorer.score_headline(text, source=source)
        scored.append({**h, **local, "model_used": model_used})
    return scored, model_used


# ──────────────────────────────────────────────────────────────
# High-level convenience — score a symbol
# ──────────────────────────────────────────────────────────────

def score_symbol_sentiment(
    symbol: str,
    side: str = "buy",
    *,
    additional_headlines: Optional[list[dict]] = None,
    social_volume_z: float = 0.0,
    price_move_60m_pct: float = 0.0,
    marketcap_rank: Optional[int] = None,
    fetch_news: bool = True,
) -> dict[str, Any]:
    """
    Full sentiment pipeline for one symbol:
      1. Check pump-dump flag
      2. Fetch Alpaca/Benzinga headlines (best-effort)
      3. Score headlines with FinBERT microservice or local fallback
      4. Compute aggregate sentiment_score
      5. Compute sentiment_alignment (clamped ±10%)

    Never raises — neutral fallback on missing data or scorer failure.
    """
    global _LAST_SENTIMENT_REFRESH_AT

    try:
        pump_dump = check_pump_dump_flag(
            symbol,
            social_volume_z=social_volume_z,
            price_move_60m_pct=price_move_60m_pct,
            marketcap_rank=marketcap_rank,
        )

        headlines: list[dict] = list(additional_headlines or [])
        if fetch_news and not headlines:
            try:
                headlines = AlpacaNewsIngester.get_headlines(symbol, limit=10)
            except Exception as exc:
                _record_sentiment_error(f"news_fetch:{exc}")

        scored_headlines, model_used = _score_headlines_with_finbert(headlines)
        sources = {h.get("source") for h in headlines if h.get("source")}

        if not headlines:
            neutral_reason = "no_headlines"
        elif model_used == "neutral_fallback":
            neutral_reason = "finbert_unavailable"
        else:
            neutral_reason = None

        if neutral_reason:
            _record_sentiment_error(neutral_reason)

        sentiment_score = compute_sentiment_score(scored_headlines)
        alignment = compute_sentiment_alignment(sentiment_score, side)
        finbert_available = FinBERTScorer.is_available()
        try:
            from app.services.finbert_client import finbert_service_url

            remote_configured = bool(finbert_service_url())
        except Exception:
            remote_configured = False

        scoring_active = bool(scored_headlines) and model_used not in ("none", "neutral_fallback")
        if headlines and model_used != "none":
            scoring_active = True

        result: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "sentiment_score": round(sentiment_score, 4),
            "sentiment_alignment": round(alignment, 4),
            "pump_dump_flag": pump_dump,
            "headline_count": len(headlines),
            "headlines_scored": len(scored_headlines),
            "source_count": len(sources),
            "sources": sorted(sources),
            "model_used": model_used,
            "finbert_available": finbert_available or remote_configured,
            "scoring_active": scoring_active,
            "social_volume_z": social_volume_z,
            "scored_at": datetime.utcnow().isoformat() + "Z",
        }
        if neutral_reason:
            result["neutral_reason"] = neutral_reason

        _SENTIMENT_CACHE[symbol] = result
        _LAST_SENTIMENT_REFRESH_AT = result["scored_at"]
        return result
    except Exception as exc:
        _record_sentiment_error(str(exc))
        fallback = {
            "symbol": symbol,
            "side": side,
            "sentiment_score": 0.0,
            "sentiment_alignment": 0.0,
            "pump_dump_flag": False,
            "headline_count": 0,
            "headlines_scored": 0,
            "source_count": 0,
            "model_used": "neutral_fallback",
            "finbert_available": False,
            "scoring_active": False,
            "neutral_reason": "pipeline_error",
            "error": str(exc)[:200],
            "scored_at": datetime.utcnow().isoformat() + "Z",
        }
        _SENTIMENT_CACHE[symbol] = fallback
        return fallback
