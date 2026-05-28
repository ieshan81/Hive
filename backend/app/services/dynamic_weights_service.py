"""AI-adjustable ranking weights — stored in config, not hardcoded."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session

from app.config import settings
from app.services.config_manager import ConfigManager
from app.services.universe_ranking_service import universe_rank_weights

logger = logging.getLogger(__name__)

UNIVERSE_WEIGHT_KEYS = (
    "w_liquidity",
    "w_spread",
    "w_volume_spike",
    "w_atr",
    "w_freshness",
    "w_cost_efficiency",
)

PORTFOLIO_WEIGHT_KEYS = (
    "w_signal_strength",
    "w_confidence",
    "w_edge_over_cost",
    "w_spread_quality",
    "w_liquidity",
    "w_volatility_anomaly",
    "w_memory_penalty",
    "w_correlation_penalty",
)


def _normalize_positive(weights: dict[str, float], keys: tuple[str, ...]) -> dict[str, float]:
    raw = {k: max(0.0, float(weights.get(k, 0))) for k in keys}
    total = sum(raw.values())
    if total <= 0:
        return {k: 1.0 / len(keys) for k in keys}
    return {k: round(raw[k] / total, 4) for k in keys}


def get_dynamic_weights(session: Session) -> dict[str, Any]:
    cfg = ConfigManager(session).get_current()
    uni = universe_rank_weights(cfg)
    ranking = cfg.get("ranking") or {}
    last = (cfg.get("ranking_meta") or {}) if isinstance(cfg.get("ranking_meta"), dict) else {}
    return {
        "status": "ok",
        "ai_managed": bool(ranking.get("ai_managed", True)),
        "universe_ranking": uni,
        "portfolio_ranking": {k: float(ranking.get(k, 0)) for k in PORTFOLIO_WEIGHT_KEYS if k in ranking},
        "min_rank_score": float(
            (cfg.get("universe_ranking") or {}).get("min_rank_score")
            or ranking.get("min_rank_score")
            or 0.28
        ),
        "last_adjustment": last,
        "updated_at": last.get("updated_at"),
    }


def apply_weights(
    session: Session,
    *,
    universe_weights: Optional[dict[str, float]] = None,
    portfolio_weights: Optional[dict[str, float]] = None,
    min_rank_score: Optional[float] = None,
    changed_by: str = "operator",
    reason: str = "Manual weight update",
) -> dict[str, Any]:
    mgr = ConfigManager(session)
    cfg = mgr.get_current()
    patch: dict[str, Any] = {
        "ranking_meta": {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "changed_by": changed_by,
            "reason": reason,
        }
    }
    if universe_weights:
        patch["universe_ranking"] = _normalize_positive(universe_weights, UNIVERSE_WEIGHT_KEYS)
    if portfolio_weights:
        norm = _normalize_positive(portfolio_weights, PORTFOLIO_WEIGHT_KEYS)
        patch["ranking"] = {**cfg.get("ranking", {}), **norm, "ai_managed": True}
    if min_rank_score is not None:
        patch.setdefault("universe_ranking", {})
        patch["universe_ranking"]["min_rank_score"] = max(0.05, min(0.95, float(min_rank_score)))
        patch.setdefault("ranking", {})
        patch["ranking"]["min_rank_score"] = patch["universe_ranking"]["min_rank_score"]

    proposal = mgr.propose(_deep_merge_patch(cfg, patch), changed_by=changed_by, reason=reason)
    active = mgr.activate_proposal(proposal.id)
    return {
        "status": "ok",
        "proposal_id": proposal.id,
        "config_version": active.version,
        "weights": get_dynamic_weights(session),
    }


def _deep_merge_patch(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def suggest_weights_with_ai(session: Session, context: Optional[dict] = None) -> dict[str, Any]:
    """Gemini proposes universe ranking weights from recent funnel + scores."""
    current = get_dynamic_weights(session)
    if not settings.gemini_configured:
        return _heuristic_weights(session, current, note="Gemini not configured — heuristic rebalance")

    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = {
            "task": "Rebalance universe_ranking weights for paper crypto exploration.",
            "constraints": {
                "keys": list(UNIVERSE_WEIGHT_KEYS),
                "sum_must_equal": 1.0,
                "min_rank_score_range": [0.15, 0.45],
                "paper_only": True,
            },
            "current_weights": current.get("universe_ranking"),
            "market_context": context or {},
        }
        model = settings.gemini_model_for("quick")
        resp = client.models.generate_content(
            model=model,
            contents=(
                "Return ONLY JSON: "
                '{"universe_weights":{...},"min_rank_score":0.28,"reasoning":"..."} '
                f"Input: {json.dumps(prompt)[:6000]}"
            ),
        )
        text = (resp.text or "").strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        parsed = json.loads(text)
        uw = parsed.get("universe_weights") or parsed.get("universe_ranking") or {}
        mrs = parsed.get("min_rank_score")
        reason = str(parsed.get("reasoning") or "AI weight rebalance")[:500]
        return apply_weights(
            session,
            universe_weights=uw,
            min_rank_score=float(mrs) if mrs is not None else None,
            changed_by="ai_advisor",
            reason=reason,
        )
    except Exception as exc:
        logger.warning("AI weight suggest failed: %s", exc)
        return _heuristic_weights(session, current, note=str(exc)[:200])


def _heuristic_weights(session: Session, current: dict, note: str) -> dict[str, Any]:
    """Shift weight toward freshness/edge when shortlist is thin."""
    try:
        from app.services.push_pull_scoring_service import score_active_universe

        scored = score_active_universe(session, ConfigManager(session).get_current())
        scores = scored.get("scores") if isinstance(scored, dict) else []
        n = sum(1 for r in (scores or []) if r.get("pass") or r.get("entry_allowed"))
    except Exception:
        n = 0
    base = dict(current.get("universe_ranking") or universe_rank_weights(ConfigManager(session).get_current()))
    if n < 2:
        base["w_freshness"] = min(0.35, base.get("w_freshness", 0.15) + 0.08)
        base["w_cost_efficiency"] = min(0.25, base.get("w_cost_efficiency", 0.10) + 0.05)
        base["w_liquidity"] = max(0.10, base.get("w_liquidity", 0.25) - 0.05)
    return {
        **apply_weights(
            session,
            universe_weights=base,
            min_rank_score=0.25 if n < 2 else None,
            changed_by="system",
            reason=f"Heuristic rebalance: {note}",
        ),
        "ai_note": note,
    }
