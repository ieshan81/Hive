"""Caged Hive FinBERT microservice — optional Railway sidecar."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Caged Hive FinBERT Service", version="1.0.0")

_MODEL = None
_MODEL_ERROR: str | None = None
_CACHE: dict[str, dict] = {}


class ClassifyItem(BaseModel):
    id: str
    symbol: str = ""
    source: str = "manual"
    text: str = Field(min_length=1, max_length=8000)


class ClassifyRequest(BaseModel):
    items: list[ClassifyItem]


def _load_model() -> None:
    global _MODEL, _MODEL_ERROR
    if _MODEL is not None or _MODEL_ERROR:
        return
    if os.environ.get("FINBERT_DISABLE", "").strip() in ("1", "true", "yes"):
        _MODEL_ERROR = "disabled_by_env"
        return
    try:
        from transformers import pipeline

        _MODEL = pipeline(
            "sentiment-analysis",
            model=os.environ.get("FINBERT_MODEL", "ProsusAI/finbert"),
            tokenizer=os.environ.get("FINBERT_MODEL", "ProsusAI/finbert"),
            device=-1,
        )
    except Exception as exc:
        _MODEL_ERROR = str(exc)[:300]


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _classify_one(item: ClassifyItem) -> dict[str, Any]:
    t0 = time.perf_counter()
    h = _text_hash(item.text)
    if h in _CACHE:
        out = dict(_CACHE[h])
        out["id"] = item.id
        out["symbol"] = item.symbol
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        out["cached"] = True
        return out

    _load_model()
    if _MODEL is None:
        return {
            "id": item.id,
            "symbol": item.symbol,
            "label": "neutral",
            "score": 0.0,
            "positive_prob": 0.0,
            "neutral_prob": 1.0,
            "negative_prob": 0.0,
            "model": "ProsusAI/finbert",
            "text_hash": h,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "status": "unavailable",
            "error": _MODEL_ERROR or "model_not_loaded",
        }

    try:
        raw = _MODEL(item.text[:512])[0]
        label = str(raw.get("label", "neutral")).lower()
        score = float(raw.get("score", 0.5))
        pos = score if "pos" in label else 0.0
        neg = score if "neg" in label else 0.0
        neu = score if "neu" in label else max(0.0, 1.0 - pos - neg)
        out = {
            "id": item.id,
            "symbol": item.symbol,
            "label": "positive" if "pos" in label else "negative" if "neg" in label else "neutral",
            "score": score,
            "positive_prob": pos,
            "neutral_prob": neu,
            "negative_prob": neg,
            "model": "ProsusAI/finbert",
            "text_hash": h,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "status": "ok",
        }
        _CACHE[h] = out
        return out
    except Exception as exc:
        return {
            "id": item.id,
            "symbol": item.symbol,
            "label": "neutral",
            "score": 0.0,
            "positive_prob": 0.0,
            "neutral_prob": 1.0,
            "negative_prob": 0.0,
            "model": "ProsusAI/finbert",
            "text_hash": h,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "status": "error",
            "error": str(exc)[:200],
        }


@app.get("/health")
def health():
    _load_model()
    return {
        "status": "ok" if _MODEL else "degraded",
        "model_loaded": _MODEL is not None,
        "error": _MODEL_ERROR,
    }


@app.get("/model/status")
def model_status():
    _load_model()
    return {
        "model": "ProsusAI/finbert",
        "loaded": _MODEL is not None,
        "error": _MODEL_ERROR,
        "cache_size": len(_CACHE),
    }


@app.get("/metrics")
def metrics():
    return {"cache_entries": len(_CACHE), "model_loaded": _MODEL is not None}


@app.post("/sentiment/classify")
def classify(req: ClassifyRequest):
    return {"items": [_classify_one(i) for i in req.items[:32]]}


@app.post("/sentiment/batch")
def batch(req: ClassifyRequest):
    return {"items": [_classify_one(i) for i in req.items[:64]]}
