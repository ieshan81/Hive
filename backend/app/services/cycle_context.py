"""Request-scoped cycle context for correlating logs and errors."""

from __future__ import annotations

from contextvars import ContextVar

current_cycle_run_id: ContextVar[str | None] = ContextVar("current_cycle_run_id", default=None)
