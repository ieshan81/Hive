"""Banned vibe terms must not appear in user-facing src copy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = (ROOT / "src" / "app", ROOT / "src" / "components")

BANNED = (
    "AI brain",
    "AI Fund Manager",
    "AI Manager",
    "Hive Brain",
    "Hive Mind decides",
    "Sentience",
    "Clean Mind",
    "Brain maintenance",
)


def main() -> None:
    hits: list[str] = []
    for base in SCAN:
        for path in base.rglob("*"):
            if path.suffix not in (".tsx", ".ts", ".css"):
                continue
            if "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for term in BANNED:
                if term in text:
                    hits.append(f"{path.relative_to(ROOT)}: {term}")
    if hits:
        print("BANNED TERMS FOUND:")
        for h in hits:
            print(f"  {h}")
        sys.exit(1)
    print("verify_ui_no_vibe_terms: PASS")


if __name__ == "__main__":
    main()
