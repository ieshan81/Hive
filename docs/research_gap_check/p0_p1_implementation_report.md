# P0/P1 Validation Safety Hardening — Implementation Report

Date: 2026-06-02
Branch: `hardening/p0-p1-validation-safety`
Validation run: `paper_validation_run_001` (preserved — no rebuild, no nuke, no history deleted)

This is a safety/governance hardening PR, not a trading-performance PR. **No live trading enabled,
no paper orders submitted, no `dry_run:false`, no gates loosened, no strategy/scoring/sizing changes.**

## Phase-by-phase

### Phase 1 — P0 rebuild protection (commit `P0: protect rebuild during validation`)
- Files: `app/services/rebuild_guard.py` (new), `app/v2/rebuild.py`, `app/routers/cockpit.py`, `scripts/verify_rebuild_requires_phrase.py` (new).
- `/api/rebuild` → `full_rebuild` now passes through `rebuild_guard`: requires phrase `"REBUILD CAGED HIVE"` and, during an active validation run, an override reason + `engines_stopped_ack`. On refusal `DangerZoneService.nuke_everything` is **never reached**. Codes: `REBUILD_BLOCKED_DURING_VALIDATION` / `CONFIRMATION_PHRASE_REQUIRED` / `VALIDATION_RUN_OVERRIDE_REQUIRED`. Audited (no secrets). Danger-zone `"NUKE CAGED HIVE"` phrase preserved.
- **Gate result: PASS** — `verify_rebuild_requires_phrase` (refused without/wrong phrase + during run; nuke not called; live locked; 0 orders). compile PASS.

### Phase 2 — P1 route-local operator auth (commit `P1: add route-local operator auth to mutating routes`)
- Files: `app/routers/{api,backtesting,candle_lab,fast_training,market_meme,market_sessions,memory_brain,settings_brain,symbol_identity}.py`, `scripts/verify_mutating_routes_have_operator_dependency.py` (new).
- Added local `Depends(require_operator_token)` to **46** mutating POST routes (paper exec, kill switch, reconciliation, promotion, memory mutations, positions sync/refresh, ai review, consolidation, fast-training, settings, symbol identity, etc.). Global middleware kept. All routes are under `/api` (already token-gated) → no behavior change for authorized callers.
- **Gate result: PASS** — scanner: 167 mutating routes all have local operator auth or are allowlisted; rebuild/danger-zone never unprotected. compile + `npm run test:api` PASS.

### Phase 3 — P1 paper protections fail-closed (commit `P1: fail closed on paper protection context errors`)
- Files: `app/services/paper_trade_protections.py`, `scripts/verify_paper_trade_protections_fail_closed.py` (new).
- A context read failure / missing session now sets `ProtectionContext.degraded`; `run_all_protections` **fails closed for NEW ENTRIES** (`PROTECTIONS_DEGRADED_FAIL_CLOSED`, codes incl. `DB_CONTEXT_UNAVAILABLE` / `PAPER_PROTECTION_CONTEXT_UNAVAILABLE`), surfaced in diagnostics. Exits are never gated by this module. Configurable (`protections.fail_closed_on_degraded`, default True). Preflight/cage unchanged (additive).
- **Gate result: PASS** — `verify_paper_trade_protections_fail_closed`. compile PASS.

### Phase 4 — P1 promotion criteria single source (commit `P1: unify promotion criteria reporting`)
- Files: `app/services/promotion_criteria.py` (new), `app/services/promotion_readiness_service.py`, `app/services/promotion_service.py`, `app/services/diagnostic_bundle_latest.py`, `scripts/verify_promotion_criteria_single_source.py` (new).
- One authoritative source: `operational_readiness_check` (7d/5t — early signal, never controls live) vs `promotion_to_pre_live_criteria` (90d/100t — the gate that governs live/pre-live). No new thresholds invented (both read existing config). `PromotionService`, `PromotionReadinessService`, and the diagnostics bundle all report the same source; diagnostics show `active_validation_run_id` + both criteria + which controls live. `ready_for_tiny_live_request` now requires the **stricter** pre-live criteria (tightened), so 7/5 alone can't be live-ready. `shift_to_live_allowed` stays false; live locked.
- **Gate result: PASS** — `verify_promotion_criteria_single_source`. compile PASS.

### Phase 5 — P1 stock-lane policy gate (commit `P1: add explicit stock lane policy gate`)
- Files: `app/services/stock_lane_policy.py` (new), `app/config.py`, `app/services/default_config.py`, `app/services/stock_data_readiness_service.py`, `scripts/verify_stock_lane_policy_gate.py` (new).
- `STOCK_LANE_MODE = disabled / readiness_only / paper_allowed_with_fresh_data / sip_required` (env `STOCK_LANE_MODE` or `stock_lane.mode`; **default `readiness_only`**). Default ⇒ equities are readiness-checked but **cannot place paper entries** during the validation run. Blockers: `STOCK_LANE_POLICY_BLOCKED` / `STOCK_BARS_STALE` / `STOCK_FEED_NOT_APPROVED` / `STOCK_MARKET_CLOSED`. `/api/stock-data/readiness` + the diagnostic bundle expose `stock_lane_mode` / `stock_entries_allowed` / `stock_lane_blocker`. Crypto never evaluated by this gate.
- **Gate result: PASS** — `verify_stock_lane_policy_gate` (mode × freshness × market × feed matrix) + `verify_stock_readiness_requires_fresh_bars`. compile + `npm run test:api` PASS.

## Final verifier result (Phase 6)
- compile (`app` + `scripts`): **PASS**
- 5 new P0/P1 verifiers: **PASS**
- Existing DB-free battery (6 stock + 2 bundle + no-secret-leak + alpaca-paper-env): **PASS**
- `npm run test:api` (5/5) + `npm run build`: **PASS**
- DB-dependent verifiers (live-lock flags, trading-cage architecture, reset-readiness, broker submit-path scanner) require a live `DATABASE_URL`; they run in the deploy environment and are confirmed via the production smoke (live locked, broker paper). They were not run in the keyless local sandbox.

## Required answers
- **Orders submitted by this task:** NO (every verifier is static/unit/mocked; no `dry_run:false`).
- **Live stayed locked:** YES (`live_trading_enabled=False`, `live_orders_enabled=False`, live lock locked; no live flags changed).
- **`paper_validation_run_001` preserved:** YES (no `/api/rebuild`, no danger-zone nuke/reset; epoch + $200 baseline intact).
- **Stock lane:** blocked / policy-gated — default `readiness_only` ⇒ no stock paper entries; current data is stale (`STOCK_BARS_STALE`) regardless.
- **Crypto:** remains active (independent 24/7 lane, unaffected by any phase).

## Unresolved (P2 — deferred, per p0_p1_fix_plan.md)
- Alpaca adapter submit guard config-aware (defense-in-depth; normal path already caged).
- Forensic diagnostic export read side-effects (`commit()`/`expire_all()`) — latest bundle is the default; avoid forensic during active cycles until refactored.
- Split `ConfigManager.get_current()` pure-read vs migration writes.
- Verify `skip_entry_safety_snapshot_gates` cannot permit stale-data orders (write verifier first).
- Prove `paper_quarantined` memory influence is negative-only.
- Broker-native stop/bracket feasibility (Alpaca paper/crypto) — external API confirmation.
- Narrow operator-proxy prefixes by risk class.
- External: Alpaca SIP authorization decision (whether equities should be hard-disabled until SIP) — drives whether `STOCK_LANE_MODE` should be `disabled` vs `readiness_only`.
