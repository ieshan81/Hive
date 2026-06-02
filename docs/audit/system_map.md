# PHASE 2 — Hive System Map

A forensic map of the real engine. Companion files: [endpoint_map.md](endpoint_map.md),
[trading_lifecycle.md](trading_lifecycle.md), [database_model_map.md](database_model_map.md),
[frontend_backend_mapping.md](frontend_backend_mapping.md).

## Core services (backend/app/services unless noted)

| Service | File | Role | Order-capable? | Mutates config? |
|---|---|---|---|---|
| AutonomousAlphaFactoryService | `autonomous_alpha_factory_service.py` | Research/scorecards/near-misses/bootstrap; no order authority | No | No |
| AlphaResearchReadModelService | `alpha_research_read_model_service.py` | Read model for `/api/alpha-factory/*` (status, scorecards, near-misses, session, paper-exploration) | No | No |
| PaperExplorationService | `paper_exploration_service.py` | Near-miss exploration lane: eligibility, scoring, broker-validity, permission, submit, promotion gate, set-cap | Yes (via cage) | Yes (set-cap only, bounded) |
| PaperExecutionService | `paper_execution_service.py` | Official order submit path: quote refresh → cage → Alpaca paper → record | **Yes (only submitter)** | No |
| ExecutionCage | `trading_cage/execution_cage.py` | Deterministic gate facade: paper guard → kill switch → cooldown → reconciliation → quote → cost → allocator → preflight → crypto validator | Gate | No |
| run_preflight | `execution_preflight.py` | Final hard gates (live lock, broker paper, kill switch, portfolio, dup, cost, stop-loss, min-notional) | Gate | No |
| paper_exploration_guard | `trading_cage/paper_exploration_guard.py` | Canonical probe-validity + kill-switch-override helpers (shared by cage + preflight) | No | No |
| KillSwitchService | `kill_switch_service.py` | entries vs exits; daily-drawdown vs catastrophic; 4-lane permission | No | No |
| ExitMonitor / exit services | `exit_monitor_service.py`, `exit_decision_service.py`, `dynamic_exit_levels_service.py` | Stop/TP/trailing/invalidation/max-hold; exits use broker truth | Yes (exits) | No |
| BrokerReconciliationService | `broker_reconciliation_service.py` | Broker-truth reconciliation; drift halts entries | No | No |
| ClosedTradeOutcomeService | `closed_trade_outcome_service.py` | Canonical closed-trade outcome (one per trade) from ledger+OrderRecord | No | No (DB cleanup) |
| MemoryEvidenceConsolidatorV2 | `memory_evidence_consolidator_v2.py` | Consolidates scorecards/sessions into LessonNode; raw hidden | No | No |
| order_ledger_service | `order_ledger_service.py` | FIFO buy/sell pairing → trades_history (canonical realized P/L) | No | No |
| ConfigManager | `config_manager.py` | Versioned config activate/history; audited | n/a | Yes (audited) |
| MissionControlReadModel | `mission_control_read_model.py` | Cockpit/mission-control truth incl. `_execution_safety` (4 lanes) | No | No |
| PaperSettingsService | `paper_settings_service.py` | Readiness + `set_paper_daily_drawdown` (bounded, AI-forbidden, confirmation) | No | Yes (kill.daily_drawdown_pct only) |
| AlpacaAdapter | `alpaca_adapter.py` | Broker client (paper); quotes, account sync, order submit | Yes (broker) | No |
| AutonomousAlphaScheduler | `autonomous_alpha_scheduler.py` | Research scheduler (no order authority) | No | Yes (scheduler_enabled) |

## Order-capable paths (the only ways an order can reach the broker)
1. `PaperExecutionService.submit_candidate` → `ExecutionCage.validate_submit` → `run_preflight` → `AlpacaAdapter` (paper). This is the **single** submit path; exploration, standard paper, and exits all route through it.
2. There is **no** live submit path reachable from paper exploration (proven by `verify_no_live_path_from_paper_exploration`).

## Safety invariants (verified across PRs #19–#30 + this audit)
- Live locked: `execution.live_orders_enabled=false`, `live_trading_enabled=false`, promotion stage `PAPER`, broker URL paper. Preflight blocks `LIVE_TRADING_LOCKED` / `BROKER_NOT_PAPER`.
- Kill switch blocks **new entries only**; exits always allowed. Catastrophic switches (manual/max-drawdown/weekly/system-health) block even exploration; daily-drawdown is the only overridable switch and only for a marked paper probe.
- Exploration caps: notional ≤ $12 (ceiling $25, operator-set, never silent), ≤1 position, ≤3 entries/day.
- Near-miss is never promoted directly to `paper_candidate`; promotion needs ≥20 closed trades + PF>1.10 + positive expectancy.
- AI/Gemini/Kronos/session signal alone cannot place orders or promote.

## Database model map (summary; see database_model_map.md)
`OrderRecord` (orders) · `TradeRecord` (trades) · `PositionSnapshot` · `ExecutionLog` · `PaperExperimentOutcome` (now canonical) · `AlphaScorecard` (+ session fields) · `LessonNode` (memory) · `ConfigCurrent`/`ConfigHistory` · `ResearchBacktestRun` · `KillSwitchEvent` · `SettingsActionAudit`.

## Schedulers / loops (heartbeat audit — see trading_logic_audit.md §heartbeat)
- Research/learning scheduler: produces scorecards/near-misses; **no order authority**.
- Paper autopilot cycle: the decision loop that can submit standard paper entries through the cage.
- Exploration lane: operator-triggered (`POST /api/alpha-factory/run-exploration`); not auto-fired by a scheduler.
- **Gap (documented):** the explicit two-loop split (fast candle heartbeat that only manages exits/quotes vs. slower decision loop that gates new entries) is partially present but not cleanly separated. See trading_logic_audit and reset plan.
