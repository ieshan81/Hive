"""Phase 2 verifier: every mutating/admin route has a local operator dependency.

Static AST scan of backend/app/routers/*.py: each POST/PUT/PATCH/DELETE route must declare a
local Depends(require_operator_token) (defense-in-depth beyond the global middleware), or be
explicitly allowlisted here as a safe read-only/no-op exception. /api/rebuild and danger-zone
mutation routes must NEVER be exposed without local auth.
"""

import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROUTERS = BACKEND / "app" / "routers"
sys.path.insert(0, str(BACKEND))

# Explicitly allowlisted mutating routes that are safe to expose without a local operator dep,
# because they are read-only computations / idempotent no-ops / public probes. (file, method, path) -> reason
ALLOWLIST: dict[tuple, str] = {
    ("operator_proxy.py", "post", "/api/operator-proxy/{path:path}"): "proxy itself injects+verifies operator token downstream",
    ("health.py", "post", "/api/health/echo"): "read-only echo, no mutation",
}


def _has_operator_dep(func: ast.FunctionDef) -> bool:
    defaults = list(func.args.defaults) + [d for d in func.args.kw_defaults if d is not None]
    for d in defaults:
        if isinstance(d, ast.Call):
            fn = d.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname == "Depends":
                for a in d.args:
                    nm = a.attr if isinstance(a, ast.Attribute) else getattr(a, "id", "")
                    if "require_operator_token" in str(nm):
                        return True
    return False


def _mutating(func: ast.FunctionDef) -> list[tuple[str, str]]:
    out = []
    for dec in func.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            method = dec.func.attr.lower()
            if method in ("post", "put", "patch", "delete"):
                path = "?"
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    path = str(dec.args[0].value)
                out.append((method, path))
    return out


def main() -> None:
    violations: list[str] = []
    rebuild_danger_unprotected: list[str] = []
    total = 0
    for py in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8-sig", errors="ignore"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = _mutating(node)
            if not routes:
                continue
            has = _has_operator_dep(node)
            for method, path in routes:
                total += 1
                key = (py.name, method, path)
                if has:
                    continue
                if key in ALLOWLIST:
                    continue
                violations.append(f"{py.name}:{node.name} [{method.upper()} {path}] missing Depends(require_operator_token)")
                low = f"{path}".lower()
                if "rebuild" in low or "danger" in low or "nuke" in low:
                    rebuild_danger_unprotected.append(f"{py.name} {method.upper()} {path}")

    if violations:
        print(f"[scan] {len(violations)} unprotected mutating route(s):")
        for v in violations:
            print("   -", v)
    assert not rebuild_danger_unprotected, \
        "CRITICAL: rebuild/danger-zone mutation route without local operator auth:\n  " + "\n  ".join(rebuild_danger_unprotected)
    assert not violations, (
        f"{len(violations)} mutating route(s) lack a local operator dependency (add Depends(require_operator_token) "
        f"or allowlist with reason):\n  " + "\n  ".join(violations)
    )
    print(f"verify_mutating_routes_have_operator_dependency: PASS ({total} mutating routes; all have local operator auth or are allowlisted)")


if __name__ == "__main__":
    main()
