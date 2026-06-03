"""Shadow Trading League — promotion ladder levels (learning only, no broker authority)."""

from __future__ import annotations

LEVEL_OBSERVED = 0
LEVEL_SHADOW_TRADE = 1
LEVEL_SHADOW_PROVEN = 2
LEVEL_PAPER_CANDIDATE = 3

LEVEL_LABELS = {
    LEVEL_OBSERVED: "observed_setup",
    LEVEL_SHADOW_TRADE: "shadow_trade",
    LEVEL_SHADOW_PROVEN: "shadow_proven_setup",
    LEVEL_PAPER_CANDIDATE: "paper_candidate",
}

STATUS_OBSERVED = "observed"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_VOID = "void"

DATA_EXECUTION_GRADE = "execution_grade"
DATA_DELAYED = "delayed"
DATA_STALE = "stale"
DATA_NOT_BROKER_QUALITY = "not_broker_quality"
