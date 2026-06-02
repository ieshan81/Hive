"""Phase 11 verifier: operator-proxy allowlist is narrowed by risk class.

Asserts the proxy denies /api/rebuild and /api/danger-zone/* (destructive), has no wildcard, classifies
paths by risk, and runs the deny check before any allow.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TS = ROOT / "src" / "lib" / "operatorProxyAllowlist.ts"


def main() -> None:
    src = TS.read_text(encoding="utf-8-sig", errors="ignore")

    # Destructive routes are explicitly denied.
    assert "DENIED_EXACT_PATHS" in src and '"/api/rebuild"' in src, "rebuild must be denied"
    assert "DENIED_PREFIXES" in src and '"/api/danger-zone/"' in src, "danger-zone must be denied"
    # Danger-zone must NOT be in the allowed exact paths anymore.
    allowed_block = src.split("ALLOWED_POST_EXACT_PATHS", 1)[1].split("]", 1)[0]
    assert "danger-zone" not in allowed_block, "danger-zone must be removed from the allowed exact paths"
    assert "/api/rebuild" not in src.split("ALLOWED_POST_PREFIXES", 1)[1].split("]", 1)[0], "rebuild must not be an allowed prefix"

    # No wildcard.
    assert '"/api/*"' not in src.split("PROXY_RISK_CLASSES", 1)[0] or 'p === "/api/*"' in src, "no wildcard allow"
    assert 'p === "/api/" || p === "/api/*"' in src or "p === \"/api/*\"" in src, "must explicitly reject bare/wildcard /api"

    # Deny runs before allow.
    fn = src.split("export function isOperatorProxyPathAllowed", 1)[1]
    assert "if (isDenied(p)) return false;" in fn, "isOperatorProxyPathAllowed must deny before allowing"
    deny_idx = fn.find("isDenied(p)")
    allow_idx = fn.find("ALLOWED_POST_EXACT_PATHS")
    assert deny_idx != -1 and allow_idx != -1 and deny_idx < allow_idx, "deny check must precede the allow check"

    # Risk classification present, destructive for rebuild + danger-zone.
    assert "PROXY_RISK_CLASSES" in src, "risk classification map missing"
    rc = src.split("PROXY_RISK_CLASSES", 1)[1]
    assert '"/api/rebuild": { class: "destructive"' in rc and '"/api/danger-zone/": { class: "destructive"' in rc, \
        "rebuild + danger-zone must be classed destructive"

    print("verify_operator_proxy_allowlist_risk_classes: PASS (rebuild + danger-zone denied; no wildcard; deny-before-allow; risk-classified)")


if __name__ == "__main__":
    main()
