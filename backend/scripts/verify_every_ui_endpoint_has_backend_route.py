"""Every /api/... endpoint the frontend calls resolves to a real backend route.

Scans src/ for apiGet/apiPost/... ("/api/...") literals, normalizes (strips query strings and
${...}/:param segments), and asserts each maps to a registered FastAPI route (with {param}
wildcards). Catches dead frontend calls to removed/renamed/typo'd routes.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

_CALL = re.compile(r"""api(?:Get|Post|PostOperator|Delete|Put|Patch)\s*(?:<[^>]*>)?\s*\(\s*[`"']([^`"']+)""")


def _frontend_paths() -> set[str]:
    out: set[str] = set()
    for f in SRC.rglob("*.ts*"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in _CALL.findall(text):
            if "/api/" not in m:
                continue
            p = m.split("?")[0].split("#")[0]
            if "/api/" not in p:
                continue
            p = "/api/" + p.split("/api/", 1)[1]
            out.add(p.rstrip("/") or "/")
    return out


def _normalize(p: str) -> str:
    # Replace template/dynamic segments with a single wildcard token.
    segs = []
    for seg in p.split("/"):
        if not seg:
            segs.append(seg)
            continue
        if "${" in seg or seg.startswith(":") or seg.isdigit():
            segs.append("*")
        else:
            segs.append(seg)
    return "/".join(segs)


def _route_data(app) -> tuple[list[re.Pattern], list[str]]:
    pats, raw = [], []
    for r in app.routes:
        path = getattr(r, "path", None)
        if not path or not path.startswith("/api"):
            continue
        clean = path.rstrip("/") or "/"
        raw.append(clean)
        rx = re.sub(r"\{[^}]+\}", "[^/]+", clean)
        pats.append(re.compile("^" + rx + "$"))
    return pats, raw


def _covered(norm_path: str, pats: list[re.Pattern], raw: list[str]) -> bool:
    candidate = norm_path.replace("*", "WILD")  # wildcard frontend segment matches [^/]+
    if any(p.match(candidate) for p in pats):
        return True
    # Dynamic-suffix call (e.g. /api/memory/bulk/${path}): the path is built from a variable, so
    # we cannot statically resolve the tail. Treat it as covered if its static prefix (before the
    # first wildcard) prefixes a real backend route under that namespace.
    if "*" in norm_path:
        prefix = norm_path.split("/*", 1)[0]
        return any(rp == prefix or rp.startswith(prefix + "/") for rp in raw)
    return False


def main() -> None:
    import warnings
    warnings.filterwarnings("ignore")
    from app.main import app

    pats, raw = _route_data(app)
    missing = []
    for fp in sorted(_frontend_paths()):
        if not _covered(_normalize(fp), pats, raw):
            missing.append(fp)
    assert not missing, "Frontend calls with NO backend route:\n  " + "\n  ".join(missing)
    print(f"verify_every_ui_endpoint_has_backend_route: PASS ({len(_frontend_paths())} UI endpoints, all routed)")


if __name__ == "__main__":
    main()
