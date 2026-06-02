# PHASE 2 — Trading Lifecycle (end-to-end, with the real files at each stage)

```
Universe → Signal → Scorecard → Near-Miss → Candidate → Permission → Cage → Preflight
→ Broker Submit → Fill → Position State → Exit Monitor → Exit Order → Broker Flat
→ Trade History → Paper Outcome → (Training Outcome) → Memory Lesson → Strategy Score → Promotion/Demotion
```

| Stage | Where | Truth source | Writes |
|---|---|---|---|
| Universe | `autonomous_strategy_generator.py` (+ symbol candidates) | scanned candidates, majors-only for session/longer-horizon families | `SymbolCandidate` |
| Signal | research worker / push-pull / session families | candle-derived; research-only | `ResearchBacktestRun`, `StrategySignal` |
| Scorecard | `autonomous_alpha_factory_service._scorecard_from_backtest` | `ResearchBacktestRun` + cost model v2 + session metrics | `AlphaScorecard` |
| Near-Miss | `get_near_misses` + `PaperExplorationService.evaluate` | scorecard gates + broker validity | (read) |
| Candidate (exploration) | `PaperExplorationService.select_candidate_detailed` | best eligible **and** broker-valid near-miss | (read) |
| Permission | `KillSwitchService.evaluate_paper_exploration` + `permission()` | 4 lanes; daily-drawdown overridable, catastrophic blocks | (read) |
| Cage | `ExecutionCage.validate_submit` | paper guard → kill switch (probe override) → cooldown → reconciliation → quote → cost (probe override) → allocator → **notional cap** → preflight → crypto validator | `ExecutionLog` |
| Preflight | `run_preflight` | live lock, broker paper, kill switch (probe override + canonical), portfolio (probe skip), dup, cost, stop-loss, **min-notional ($10 crypto)**, spread | `ExecutionLog` |
| Broker Submit | `PaperExecutionService.submit_candidate` → `AlpacaAdapter` | Alpaca **paper** only; `EXPLORATION-` client_order_id preserved | `OrderRecord` (pending→submitted/filled/rejected) |
| Fill | broker payload + reconcile | `paper_order_filled` | `OrderRecord.filled_avg_price/qty`, `PositionSnapshot` |
| Position State | `PositionSnapshot` / position state services | broker truth | `PositionSnapshot` |
| Exit Monitor | `exit_monitor_service` + `exit_decision_service` + `dynamic_exit_levels_service` | stop/TP/trailing/invalidation/max-hold; **broker truth**; exits always allowed | exit `OrderRecord` |
| Exit Order → Broker Flat | same submit path (sell) | broker flat verified | `OrderRecord` (sell) |
| Trade History | `order_ledger_service.build_trade_ledger` | FIFO buy/sell pairing → realized P/L | (computed) `trades_history` |
| Paper Outcome | `ClosedTradeOutcomeService.backfill` (PR #30) | **one canonical** record per trade from ledger+OrderRecord; fee_adjusted_qty_delta; canonical_exit_reason | `PaperExperimentOutcome` |
| Memory Lesson | `MemoryEvidenceConsolidatorV2` | consolidated lesson tied to scorecard/outcome | `LessonNode` |
| Strategy Score | promotion service | scorecard verdict | `AlphaScorecard.verdict`, `StrategyRegistry` |
| Promotion/Demotion | `PaperExplorationService.can_promote_from_exploration` + `promotion.evaluate` | ≥20 closed + PF>1.10 + positive expectancy; live never auto | (gated) |

## Proven end-to-end (prior missions, evidence)
A real BTC/USD paper exploration probe: submitted → `paper_order_filled` → exit monitor → broker flat → trade history realized P/L → canonical outcome (`-0.069258`, fee delta recorded) → lane blocked a 2nd order (`exploration_max_positions:1>=1`). Real money locked throughout.

## Known gaps (carried into trading_logic_audit + reset plan)
- Two-loop heartbeat (fast manage-only vs slow decision) not cleanly separated.
- Backtest lab is thin (research backtests exist; no walk-forward/overfit lab yet — see backtesting_lab_plan).
- Memory pipeline lacks the strict RawEvent→Hypothesis→Backtest→Paper→Outcome gating (see self_correction_brain_audit).
