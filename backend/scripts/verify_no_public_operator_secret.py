"""Frontend must not reference NEXT_PUBLIC_OPERATOR_TOKEN."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    bad = []
    for pattern in ("NEXT_PUBLIC_OPERATOR", "NEXT_PUBLIC_OPERATOR_TOKEN"):
        for path in ROOT.rglob("*"):
            if path.suffix not in (".ts", ".tsx", ".js", ".jsx", ".env.example", ".md"):
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern in text:
                bad.append(str(path.relative_to(ROOT)))
    if bad:
        print("FOUND_NEXT_PUBLIC_OPERATOR:", bad)
        sys.exit(1)
    print("ALL_CHECKS_PASSED")


if __name__ == "__main__":
    main()
