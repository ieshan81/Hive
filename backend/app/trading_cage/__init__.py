"""
Deterministic paper-trading risk cage — the only path to Alpaca submission.

Architecture: scan → score → validate → allocate → submit → watch → exit → learn
Gemini and UI must never bypass this package.
"""

from app.trading_cage.cost_model import CostModelResult, evaluate_edge_after_cost_bps
from app.trading_cage.execution_cage import ExecutionCage, ExecutionCageResult
from app.trading_cage.micro_cap_allocator import MicroCapAllocator, AllocationDecision
from app.trading_cage.paper_guard import assert_paper_only, paper_guard_status
from app.trading_cage.push_pull_engine import PushPullScore, score_push_pull_setup

__all__ = [
    "assert_paper_only",
    "paper_guard_status",
    "evaluate_edge_after_cost_bps",
    "CostModelResult",
    "MicroCapAllocator",
    "AllocationDecision",
    "ExecutionCage",
    "ExecutionCageResult",
    "PushPullScore",
    "score_push_pull_setup",
]
