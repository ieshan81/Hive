"""Scan for forbidden hardcoded DOGE in production paths."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

ALLOWED_PATH_PARTS = (
    "/tests/",
    "verify_",
    "scripts/verify",
    "fixtures",
    ".md",
    "docs/",
    "default_config.py",
    "strategy_library.py",
    "ResearchLabPanel",
    "assetIcons",
    "_prod_",
    "_strat_",
    "_bundle",
    "research_lab",
    "meme_volatility",
    "strategy_conflict",
    "hardcoded_symbol_scan",
)

FORBIDDEN_PATTERNS = [
    (r'sym\s*=\s*["\']DOGE', "hardcoded sym=DOGE assignment"),
    (r'id\s*=\s*["\']position-DOGE', "hardcoded position node id"),
]


def scan_repository() -> dict:
    violations: list[dict] = []
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
            if "training_execution_service.py" in rel and "DOGE/USD" in line and "symbols[0]" not in text:
                if "sym =" in line or 'sym="' in line:
                    forbidden = True
                    hit["reason"] = "hardcoded training trade symbol"
            if forbidden and not allowed:
                violations.append(hit)
    return {
        "status": "ok" if not violations else "violations",
        "violation_count": len(violations),
        "violations": violations[:50],
        "training_selection_clean": not any("training_execution" in v["file"] for v in violations),
        "graph_production_clean": not any("hive_brain_graph" in v["file"] and "DOGE" in v.get("snippet", "") for v in violations),
    }
