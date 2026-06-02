# PHASE 6 — Memory Reset & Rebuild Plan

Companion to [self_correction_brain_audit.md](self_correction_brain_audit.md). Executed as **PR C**
(not in this PR A docs-only deliverable). No memory is deleted destructively.

## Pre-reset preservation (NEVER delete)
- Closed-trade evidence: `OrderRecord`, `TradeRecord`, `PaperExperimentOutcome` (canonical).
- Audit logs: `SettingsActionAudit`, `ConfigHistory`, `KillSwitchEvent`, `ExecutionLog`.
- Diagnostic bundle history.

## Reset steps (PR C)
1. **Export** all `LessonNode` rows to `data/archive/legacy_memory_before_reset/lessons_<ts>.json` + a summary in `docs/audit/legacy_memory_export_summary.md` (counts by memory_type/status, can_influence_ranking totals).
2. **Archive (not delete)** noisy active lessons: set `status="archived"`, `visible_to_ai=false`, `can_influence_ranking=false` for lessons not tied to a real `trade_id/order_id/outcome_id/backtest_id`.
3. **Keep active** only evidence-linked lessons (closed-trade, validated-strategy, risk incidents).
4. **Rebuild** under the typed taxonomy (7 classes) with the state machine + market-context fingerprint.
5. **Repopulate** clean memory from: closed trades (`ClosedTradeOutcomeService`), verified backtests, risk incidents (kill-switch/cooldown/stale-quote), execution failures that became tests.

## Guard verifiers (PR B/C)
- `verify_old_memory_archived_before_reset.py` — noisy active lessons archived, evidence preserved.
- `verify_memory_cannot_directly_trade.py` — no memory path reaches order submission or live flags.
- `verify_memory_hypothesis_requires_backtest.py` — hypothesis lessons cannot influence trading without a linked backtest.

## Reset-blocker? **No.**
Memory is advisory-only today (cannot trade or change risk/live), so the $200 reset run can proceed
before the typed rebuild. The rebuild improves *learning quality*, not safety.
