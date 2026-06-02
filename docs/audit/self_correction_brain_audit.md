# PHASE 6 — Self-Correction Brain & Memory Audit

Goal: Hive recognizes repeatable situations and adapts **through evidence** — not random AI memory
chaos. Central rule: **no memory may directly trade or mutate risk/live settings.**

## Current memory system (as built)
- Store: `LessonNode` (memory_type, pattern_key, evidence_json, is_consolidated, memory_level, can_influence_ranking, visible_to_ai, status).
- Writer: `MemoryEvidenceConsolidatorV2` — consolidates `AlphaScorecard` (+ session) into ONE lesson per stable `pattern_key`; supersedes verdicts in place; **raw events hidden by default**; `can_influence_ranking` only for validated candidates.
- Influence today: lessons can influence **ranking** (research) only; they do **not** mutate risk, config, or live flags, and cannot place orders. Promotion still runs through `promotion.evaluate` evidence gates.

### Findings
- ✅ Consolidation exists and dedupes (no raw spam in the meaningful set).
- ✅ Lessons are tied to a scorecard/outcome (`related_entity_*`).
- ⚠️ The strict typed pipeline below is **not yet enforced** — hypotheses, backtests, and validated strategies share the same lesson store without a hard state machine gate.
- ⚠️ Memory categories are partially present (alpha_evidence / session_* / rejected / validated) but not the full 7-class taxonomy.
- ✅ No path lets a memory directly trade or change live (to be locked by `verify_memory_cannot_directly_trade`, planned PR B).

## Required memory taxonomy (target)
1. **Raw Event** — everything; no strategy influence.
2. **Closed Trade** — entry/exit/PL/reason/hold; influences scoring only after sample.
3. **Backtest** — tested ideas; influences paper experiments only.
4. **Risk** — spread-killed-edge, dup exposure, stale quote; can block/reduce confidence.
5. **Market Regime** — vol/trend/session/correlation/liquidity; adjusts confidence/ranking.
6. **Hypothesis** — AI idea awaiting backtest; **cannot trade**.
7. **Validated Strategy** — only after backtest + paper evidence; influences ranking inside paper.

## Required pipeline (state machine — to enforce in PR C)
```
RawEvent → EvidenceMemory → Hypothesis → BacktestResult → PaperExperiment → ClosedOutcome → StrategyScore → Promotion/Demotion
```
Hard rules: raw cannot trade · AI cannot mutate risk/enable live · hypotheses must be backtested · backtest winners → tiny paper experiments · paper winners promoted, losers demoted/cooled · **every learning memory must link to** one of `trade_id / order_id / outcome_id / backtest_id / verifier_id / diagnostic_bundle_id`.

## Market-context fingerprint (to add to every signal/trade/outcome)
symbol · asset_class · session · timeframe · trend_state · volatility_state · spread_bps ·
volume/liquidity_state · BTC/ETH correlation (crypto) · SPY/QQQ regime (stocks) · regime_label ·
strategy_id · entry_reason · exit_reason · pnl_after_cost · hold_time.
Today: scorecards carry symbol/session/cost/edge; the full fingerprint is **partial** — to extend in PR C.

## Relationship graph (design — evidence-gated, never blind)
BTC↔ETH · ETH↔crypto-beta · SOL/AVAX/UNI↔high-beta crypto · SPY↔broad · QQQ↔tech/risk-on ·
NVDA↔AI/semis · VIX/rates/DXY regime context. **Affects confidence/risk only after evidence**; never auto-trades. Implement as a read-model overlay on ranking, gated behind closed-trade evidence counts.

## Memory reset (plan — executed in PR C, see memory_reset_and_rebuild_plan.md)
1. Export legacy memory to `data/archive/legacy_memory_before_reset/` + summary doc.
2. Preserve closed-trade evidence, order/trade/outcome history, audit logs (never delete).
3. Archive noisy *active* lessons (status→archived), do not hard-delete.
4. Rebuild under the typed schema; repopulate from closed trades + verified backtests + risk incidents + execution failures.

## Acceptance (target after PR C)
- No random memory can influence trades (enforced by `verify_memory_cannot_directly_trade`).
- Clean memory categories exist; hypotheses separate from approved strategies (`verify_memory_hypothesis_requires_backtest`).
- Memory ready to repopulate after reset (`verify_old_memory_archived_before_reset`).

## Verdict
Memory is **safe today** (no direct trading/live influence) but **not yet the disciplined,
typed, evidence-linked brain** the mission wants. The reset run can proceed (memory is advisory
only); the typed pipeline + fingerprint + relationship graph are **PR C follow-up**, not reset blockers.
