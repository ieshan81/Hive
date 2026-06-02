# PHASE 2 — Database Model Map (key tables)

Source: `backend/app/database.py`. Trading/safety-relevant tables (the app has more display tables).

| Model | Table | Role | Written by |
|---|---|---|---|
| `OrderRecord` | orders | broker order truth (alpaca_order_id, broker_client_order_id, side, qty, status, filled_avg_price) | PaperExecutionService |
| `TradeRecord` | trades | entry/exit/qty/pl_dollars/return_pct/status | trade recording |
| `PositionSnapshot` | position_snapshots | broker positions (qty>0) | broker sync |
| `ExecutionLog` | execution_logs | every submit attempt + gates passed/failed + reject_reason | cage/preflight/PaperExecution |
| `PaperExperimentOutcome` | paper_experiment_outcomes | **canonical closed-trade outcome** (PR #30): order ids, broker ids, EXPLORATION client ids, prices, qty_bought/sold, fee_adjusted_qty_delta, realized_pnl(_pct), canonical_exit_reason, raw_exit_trigger, trade_id, lesson_created | ClosedTradeOutcomeService + training writer |
| `AlphaScorecard` | alpha_scorecards | research scorecard + cost truth + **session metrics** | AlphaFactory |
| `LessonNode` | (memory) | consolidated lessons (memory brain) | MemoryEvidenceConsolidatorV2 |
| `ResearchBacktestRun` | research_backtest_runs | backtest evidence | research lab |
| `ConfigCurrent` / `ConfigHistory` | config | versioned config + audit | ConfigManager |
| `KillSwitchEvent` | kill_switch_events | persisted kill switches | KillSwitchService |
| `SettingsActionAudit` | settings_action_audit | operator/system action audit (incl. paper_exploration_order, set-cap, set-drawdown) | services |
| `SymbolCandidate` | symbol_candidates | scanned universe | scanners |
| `StrategySignal` | strategy_signals | signals | research |
| `StrategyRegistry` | strategy_registry | strategy stage/can_trade_paper | promotion |

## Integrity notes
- Outcome ↔ trades_history now **agree** (PR #30: realized P/L reconciled from FIFO ledger).
- `paper_experiment_outcomes` gained canonical columns via model + **startup column-repair** (`repair_database_bootstrap`) — non-destructive, idempotent.
- Closed-trade evidence (orders/trades/outcomes/execution_logs/config_history/audit) is **preservation-protected** in the reset plan.
