"""Optional research dependency probes.

Research libraries are useful, but they must never become required boot
dependencies for Railway. Probe by import name only when a status endpoint or
adapter asks for it.
"""

from __future__ import annotations

import importlib.util


OPTIONAL_RESEARCH_DEPENDENCIES = {
    "vectorbt": "vectorbt",
    "optuna": "optuna",
    "langgraph": "langgraph",
    "pyportfolioopt": "pypfopt",
    "riskfolio_lib": "riskfolio",
    "quantstats": "quantstats",
    "pgvector": "pgvector",
}


def optional_dependency_status() -> dict:
    return {
        name: {
            "available": importlib.util.find_spec(module) is not None,
            "required_for_boot": False,
            "adapter_mode": "optional_import_guard",
        }
        for name, module in OPTIONAL_RESEARCH_DEPENDENCIES.items()
    }

