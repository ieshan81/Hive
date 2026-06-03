"""Phase 0 verifier: no vibe/sentience logic in the trade/score/rank/promotion/risk decision path.

Asserts the HARD RULE: no scorecard / ranking / preflight / cage / execution code imports the renamed
former-vibe modules or reads vibe/sentience fields; the former "AI Fund Manager" (now Strategy
Reviewer) is quarantined disabled-by-default in the cycle and never gates trades; no scheduled job runs
it; the old module names have no active imports; and active frontend copy carries no vibe/sentience
language (staged branding identifiers are documented in the migration note). Read-only; compiles backend.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SRC = REPO / "src"


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return ""


# Decision-path files: ranking/scorecard/promotion + preflight/cage/risk + v2 execution. None of these
# may import the (renamed) reviewer/evidence modules or read vibe/sentience fields.
DECISION_PATH = [
    "app/services/push_pull_scoring_service.py", "app/services/push_pull_scorer.py",
    "app/services/push_pull_scan_service.py", "app/services/push_pull_engine_service.py",
    "app/services/strategy_scorecard_service.py", "app/services/promotion_criteria.py",
    "app/services/execution_preflight.py", "app/services/closing_position_preflight.py",
    "app/services/kill_switch_service.py", "app/services/stock_lane_policy.py",
    "app/services/rebuild_guard.py", "app/services/paper_trade_protections.py",
    "app/services/risk_engine.py", "app/services/crypto_push_pull.py",
    "app/v2/agent_engine.py", "app/v2/cycle_runner.py", "app/v2/live_pipeline.py",
]
# Modules a decision-path file must not import (advisory commentary / memory, not gates).
BANNED_DECISION_IMPORTS = ("strategy_reviewer", "evidence_memory_service", "ai_fund_manager",
                           "ai_learning_memory_service")
# Vibe/sentience field/var references that must not appear in decision-path logic.
BANNED_DECISION_TOKENS = ("vibe", "sentien", "intuition", "ai_review", "should_pause_strategy",
                          "should_blacklist_symbol", "instinct")
# Deleted/renamed module names that must have NO active import anywhere.
DELETED_MODULES = ("ai_fund_manager", "ai_learning_memory_service")

# Frontend hard-fail COPY (user-facing vibe/sentience language). Camel-case identifiers like
# AIFundManagerData / HiveBrainCanvas are STAGED branding (see hive_semantics_cleanup.md) and excluded.
FRONTEND_BANNED_COPY = re.compile(
    r"sentien|\bvibe|intuition|\bmood\b|\bemotion|self.?improv|AI Fund Manager|"
    r"Hive (?:feels|decides|knows|thinks|senses)|brain decides|AI decides|mystical",
    re.IGNORECASE,
)


def main() -> None:
    failures: list[str] = []

    # 1) Old module names have no active import anywhere in backend.
    for py in list((BACKEND / "app").rglob("*.py")) + list((BACKEND / "scripts").rglob("*.py")):
        txt = _read(py)
        for mod in DELETED_MODULES:
            if re.search(rf"^\s*(from app\.services\.{mod} import|import app\.services\.{mod})", txt, re.M):
                failures.append(f"{py.relative_to(REPO)} still imports deleted module '{mod}'")

    # 2) Decision-path files import no vibe/reviewer module and read no vibe/sentience field.
    for rel in DECISION_PATH:
        p = BACKEND / rel
        if not p.exists():
            continue
        txt = _read(p)
        for mod in BANNED_DECISION_IMPORTS:
            if re.search(rf"(from app\.services\.{mod} import|import.*\b{mod}\b)", txt):
                failures.append(f"decision-path {rel} imports '{mod}' (must not influence gating)")
        low = txt.lower()
        for tok in BANNED_DECISION_TOKENS:
            if tok in low:
                failures.append(f"decision-path {rel} references vibe/sentience token '{tok}'")

    # 3) Strategy Reviewer is quarantined in the cycle: disabled-by-default flag gates the review.
    cyc = _read(BACKEND / "app/services/cycle_engine.py")
    if "legacy_strategy_reviewer_enabled" not in cyc or "self.reviewer_enabled" not in cyc:
        failures.append("cycle_engine missing disabled-by-default reviewer flag (legacy_strategy_reviewer_enabled)")
    if not re.search(r"if\s+self\.reviewer_enabled\s+and", cyc):
        failures.append("cycle_engine review block is not gated by self.reviewer_enabled")

    # 4) No scheduled job runs the reviewer.
    for sched in (BACKEND / "app/services").glob("*scheduler*.py"):
        if re.search(r"StrategyReviewer|strategy_reviewer", _read(sched)):
            failures.append(f"scheduled job {sched.name} runs the Strategy Reviewer")

    # 5) Frontend active copy carries no vibe/sentience language.
    if SRC.exists():
        for f in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.tsx")) + list(SRC.rglob("*.css")):
            for i, line in enumerate(_read(f).splitlines(), 1):
                m = FRONTEND_BANNED_COPY.search(line)
                if not m:
                    continue
                # Allow the camel-case identifier "AIFundManager..." (staged), fail on the spaced copy.
                if m.group(0).lower() == "ai fund manager" and "AIFundManager" in line and "AI Fund Manager" not in line:
                    continue
                failures.append(f"frontend copy {f.relative_to(REPO)}:{i} → '{m.group(0)}'")

    # 6) Migration note exists (documents the staged branding identifiers).
    if not (REPO / "docs/simplification/hive_semantics_cleanup.md").exists():
        failures.append("missing docs/simplification/hive_semantics_cleanup.md (migration note)")

    # 7) Backend compiles.
    rc = subprocess.run([sys.executable, "-m", "compileall", "-q", str(BACKEND / "app"), str(BACKEND / "scripts")],
                        capture_output=True, text=True)
    if rc.returncode != 0:
        failures.append(f"compileall failed: {(rc.stdout + rc.stderr)[-300:]}")

    if failures:
        print("verify_no_vibe_logic_in_decision_path: FAIL")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("verify_no_vibe_logic_in_decision_path: PASS (decision path free of vibe/sentience; reviewer "
          "quarantined disabled-by-default; old modules unimported; no scheduled reviewer; frontend copy clean)")


if __name__ == "__main__":
    main()
