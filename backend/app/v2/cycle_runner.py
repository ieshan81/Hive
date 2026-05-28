"""V2 trading cycle — delegates to agent engine."""

from __future__ import annotations

from sqlmodel import Session

from app.v2.agent_engine import run_agent_cycle


def run_trading_cycle(session: Session, operator: str = "v2_cycle") -> dict:
    return run_agent_cycle(session, operator=operator)
