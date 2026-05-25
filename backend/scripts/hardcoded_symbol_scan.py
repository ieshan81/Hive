"""Scan repo for forbidden hardcoded DOGE in production paths."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ALLOWED_PATH_PARTS = (
    "/tests/",
    "/test_",
    "verify_",
    "scripts/verify",
    "fixtures",
    ".md",
    "docs/",
    "default_config.py",
    "strategy_library.py",
    "symbol_tier",
    "meme_volatility",
    "aggressive_paper_learning_service.py",  # MEME_SYMBOLS tier set only
    "strategy_conflict",
    "research_lab",
    "ResearchLabPanel",
    "assetIcons",
    "market_meme.py",  # default example body only in router default - checked separately
    "_prod_",
    "_strat_",
    "_bundle",
    "hive-diagnostic",
)

FORBIDDEN_PATTERNS = [
    (r'DOGEUSD["\']?\s*[,:\)]', "hardcoded DOGEUSD literal"),
    (r'["\']DOGE/USD["\']', "hardcoded DOGE/USD string"),
    (r'sym\s*=\s*["\']DOGE', "hardcoded sym=DOGE assignment"),
    (r'id\s*=\s*["\']position-DOGE', "hardcoded position node id"),
    (r'id\s*=\s*["\']strategy-crypto_push_pull.*DOGE', "hardcoded DOGE strategy node"),
]

PRODUCTION_GRAPH_PATHS = (
    "hive_brain_graph_service.py",
    "lesson_memory_service.py",
    "HiveMemoryGraphPanel",
    "HiveBrainCanvas",
)

PRODUCTION_TRAINING_PATHS = (
    "training_execution_service.py",
    "fast_crypto_training_loop.py",
)


def scan() -> dict:
    violations: list[dict] = []
    allowed_hits: list[dict] = []
    exts = {".py", ".tsx", ".ts"}

    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in exts:
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if "node_modules" in rel or ".next" in rel or "__pycache__" in rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "DOGE" not in text.upper():
            continue

        allowed = any(p in rel for p in ALLOWED_PATH_PARTS)
        for i, line in enumerate(text.splitlines(), 1):
            if "DOGE" not in line.upper():
                continue
            hit = {"file": rel, "line": i, "snippet": line.strip()[:120]}
            forbidden = False
            for pat, reason in FORBIDDEN_PATTERNS:
                if re.search(pat, line, re.I):
                    forbidden = True
                    hit["reason"] = reason
                    break
            if rel.endswith("market_meme.py") and "symbols" in line and "or [" in line:
                allowed = True
            if rel.endswith("training_execution_service.py") and "DOGE/USD" in line:
                forbidden = True
                hit["reason"] = "hardcoded training trade symbol selection"
            if any(g in rel for g in PRODUCTION_GRAPH_PATHS) and "DOGE" in line:
                forbidden = True
                hit["reason"] = hit.get("reason") or "DOGE in graph production code"
            if forbidden and not allowed:
                violations.append(hit)
            elif allowed:
                allowed_hits.append(hit)

    graph_clean = not any(
        v["file"] in PRODUCTION_GRAPH_PATHS or "graph" in v.get("reason", "").lower()
        for v in violations
    )
    training_clean = not any("training_execution" in v["file"] for v in violations)

    return {
        "status": "ok" if not violations else "violations",
        "violation_count": len(violations),
        "violations": violations[:50],
        "allowed_hit_count": len(allowed_hits),
        "graph_production_clean": graph_clean,
        "training_selection_clean": training_clean,
        "scanned_root": str(ROOT),
    }


if __name__ == "__main__":
    print(json.dumps(scan(), indent=2))
