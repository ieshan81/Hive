"""PR #1 root cause doc — scheduler off + no cron caller."""

ROOT_CAUSE = """
## Phase 1 — Root cause (production read-only)

- `autonomous_paper_learning.scheduler_enabled=false` in DB config
- Mission control blocker: `scheduler_off`
- Paper execution ON (`paper_orders_enabled`, `paper_entry_ready`) but no automatic ticks
- Last scan stale (>15 min) because nothing calls POST /api/autonomous-paper-learning/tick
- Shadow league enabled but count 0 (no recent push-pull ticks)
- `paper_validation_run_001` intact; live locked; broker paper

Accidental, not safety pause: paper learning was enabled without re-enabling the scheduler flag.

Fix: scheduler/enable (NOT start-fresh) + supervised-burst + Railway Cron.
"""

if __name__ == "__main__":
    print(ROOT_CAUSE.strip())
