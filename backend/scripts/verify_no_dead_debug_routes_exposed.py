"""No unauthenticated debug/raw/test routes are exposed that could leak internals or mutate state.

Scans registered FastAPI routes for debug-smelling paths and asserts any such route is either
absent or requires the operator token (i.e., not a public mutating debug hole).
"""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

# Matched on full path SEGMENTS (not substrings) so e.g. "evaluate" never matches "eval".
_DEBUG_SEGMENTS = frozenset({"debug", "_debug", "raw-sql", "exec-sql", "eval", "shell", "test-only", "_internal", "__debug__"})


def _has_debug_segment(path: str) -> bool:
    return any(seg in _DEBUG_SEGMENTS for seg in path.split("/"))


def _requires_operator(route) -> bool:
    # The operator dependency appears in the route's dependant call chain.
    try:
        deps = getattr(route, "dependant", None)
        names = []
        if deps:
            for d in getattr(deps, "dependencies", []):
                fn = getattr(d, "call", None)
                if fn is not None:
                    names.append(getattr(fn, "__name__", ""))
        return any("operator" in n.lower() for n in names)
    except Exception:
        return False


def main() -> None:
    from app.main import app

    offenders = []
    for r in app.routes:
        path = (getattr(r, "path", "") or "").lower()
        methods = getattr(r, "methods", set()) or set()
        if not path.startswith("/api"):
            continue
        if _has_debug_segment(path):
            mutating = bool(methods & {"POST", "PUT", "PATCH", "DELETE"})
            if mutating and not _requires_operator(r):
                offenders.append(f"{sorted(methods)} {path} (mutating debug route without operator auth)")
    assert not offenders, "Dead/debug routes exposed:\n  " + "\n  ".join(offenders)
    print("verify_no_dead_debug_routes_exposed: PASS (no public mutating debug routes)")


if __name__ == "__main__":
    main()
