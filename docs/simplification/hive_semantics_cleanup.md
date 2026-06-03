# Hive Semantics Cleanup — Phase 0 (remove vibe-based trading logic)

**Goal:** make Caged Hive Quant a serious, evidence-driven trading lab. Remove "vibe / sentience /
AI-fund-manager autonomy / intuition / emotion / non-evidence memory" semantics from the **decision
path**, keep the safety cage, change no trading behavior.

**Hard rule (enforced by `backend/scripts/verify_no_vibe_logic_in_decision_path.py`):**
No trade, score, rank, promotion, or risk decision may depend on any vibe/sentience field.

---

## Audit finding (the reassuring part)

The decision path was **already free of vibe logic**. None of the scoring / scorecard / ranking /
promotion / preflight / cage / risk / execution files read any vibe/sentience/AI field:

- `push_pull_scoring_service.py`, `push_pull_scorer.py`, `push_pull_scan_service.py`,
  `push_pull_engine_service.py`, `strategy_scorecard_service.py`, `promotion_criteria.py`,
  `execution_preflight.py`, `closing_position_preflight.py`, `kill_switch_service.py`,
  `stock_lane_policy.py`, `rebuild_guard.py`, `paper_trade_protections.py`, `risk_engine.py`,
  `crypto_push_pull.py`, `app/v2/agent_engine.py`, `cycle_runner.py`, `live_pipeline.py` — all clean.

The former **"AI Fund Manager"** (Gemini) was advisory commentary only: it wrote an `AIReview` row,
created an advisory memory note, and rendered a dashboard panel. Its action fields
(`should_pause_strategy`, `should_blacklist_symbol`, `strategy_status_recommendation`) were **never
executed**, and its `config_change_proposal` is **gated** (`auto_apply_allowed: False`). So it never
ranked, scored, gated, or executed a trade.

## Actions taken (Phase 0)

### Backend rename + quarantine
| Old | New | Notes |
|---|---|---|
| `ai_fund_manager.py` / `AIFundManager` | `strategy_reviewer.py` / `StrategyReviewer` | Advisory only; prompt/labels reworded ("cannot execute trades, rank symbols, change scorecards, or override risk"). |
| `ai_learning_memory_service.py` / `AILearningMemoryService` | `evidence_memory_service.py` / `EvidenceMemoryService` | Evidence-derived, advisory memories. Method + DB-category names kept stable (no data migration). |

**Quarantine:** `cycle_engine` now gates the Strategy Reviewer behind a **disabled-by-default** flag
`legacy_strategy_reviewer_enabled` (default `False`). With it off (the default), the reviewer never
runs in the decision loop — the cycle uses the deterministic system summary. Trade decisions are
already complete before the (disabled) reviewer would run.

**Config flags** (`default_config.py`):

| Flag | Default | Meaning |
|---|---|---|
| `legacy_strategy_reviewer_enabled` | `False` | Cycle runs Strategy Reviewer only when `True`. |
| `strategy_reviewer.enabled` | `False` | Documented alias; cycle uses `legacy_strategy_reviewer_enabled`. |
| `evidence_memory.enabled` | `True` | Evidence Memory generate/list (advisory only). |
| `legacy_ai_fund_manager.disabled_by_default` | `True` | Documents retired autonomous fund-manager semantics. |
| `legacy_sentience.disabled_by_default` | `True` | Documents retired sentience/vibe decision semantics. |

### Frontend copy scrubbed (user-facing)
- `AIFundManagerPanel` title → **"Strategy Reviewer"**; first-person labels → "Evidence learned" /
  "Patterns to avoid" / "Next tests queued".
- `HiveMemoryGraphPanel` / `HiveMindSection` user-facing titles → **Evidence Memory Graph** /
  **Evidence Memory**.
- `layout.tsx` description → "Evidence-driven paper-trading validation lab. Live trading locked."
- `globals.css` brand comment: "sentient" → "evidence-driven".
- `StrategyProposalsPanel` blurb: "Self-improvement suggestions from memory and confidence" →
  "Evidence-based suggestions from memory and scorecards".

### Naming map (reference)
Sentience → Learning Status · Hive Brain → Evidence Memory Graph · AI Fund Manager → Strategy
Reviewer · Vibe Confidence → Evidence Confidence · AI Decision → Strategy Review Result · Mood/Emotion
→ removed · "Hive decides" → "Hive records / compares / recommends" · Autonomous intuition →
Evidence-based blocker or scorecard.

## Retained on purpose
- **Market sentiment** (FinBERT/news): an evidence-based market-data signal, advisory, capped at
  ≤ ±10% ranking influence, cage decides. This is *not* "vibe/sentience" and is retained.
- The `AIReview` table, `aiFundManager` dashboard payload key, and `ai_*` DB category strings: kept
  for contract/data stability; the reviewer that writes them is disabled by default.

## Staged for the follow-up UI-rename PR (NOT in this PR)
These **code identifiers** remain (not user-facing copy) and can be renamed in a follow-up PR:
`HiveBrainCanvas/CustomNode/Drawer`, `CleanMindPanel`, `CockpitFunnelBrain`, `SettingsBrainMaintenance`,
`AIFundManagerPanel`/`AIFundManagerData`, `types/hiveBrain.ts`, `ai-manager/page.tsx`.

## What is NOT changing
Safety cage, live locks, risk gates, `paper_validation_run_001`, broker behavior — all unchanged.
No live trading, no forced broker trades, no `/api/rebuild`, no danger-zone reset.
