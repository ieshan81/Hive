# PHASE 5 — Trading Logic Audit

Forensic review of trading logic. Verdicts are evidence-based (code + read-only prod + verifiers
from PRs #19–#30). **No profit claims. No "ready for live".**

## SIGNAL QUALITY
- **Producer:** deterministic research backtests + push-pull / session families (`autonomous_strategy_generator.py`). No LLM produces a tradeable signal directly.
- **Timeframe / closed candle:** research runs on stored `HistoricalBar` (5Min default; 1h/4h longer-horizon family). Backtests use stored bars (closed). **Risk:** the live exploration path uses a fresh quote (mid/ask) at submit, not a confirmed-closed-candle signal — entries are candidate-driven, not strictly closed-candle-confirmed. **Action (reset run):** confirm entry signals reference closed candles, not the forming one.
- **Lookahead/survivorship:** backtests use point-in-time bars; no obvious lookahead, but **not formally proven** — flagged for the backtest lab (out-of-sample + walk-forward).
- **Stale data:** blocked — `STALE_QUOTE` gate (preflight + cage), `data_freshness_status` on scorecards.
- **Sessions / asset separation:** sessions classified (`MarketSessionService`); crypto vs stock asset_class enforced (`classify_asset`). Crypto pairs correctly classified crypto.
- **Edge demonstrated?** **NO** — `paper_candidate_count = 0`, all scorecards rejected/unproven; **no strategy has a proven positive after-cost edge yet.** This is the honest core finding.

## COST MODEL
- Spread + slippage + fee modeled; **v2 fixed the double-count** (`cost_model_version = v2_components_no_double_count`). Round-trip = spread + 2×slippage + 2×fee, clamped [floor,cap]. Fee 25 bps/side (conservative, not lowered).
- `edge_after_cost_bps` used consistently in scorecards + near-misses.
- Tiny-order distortion: **handled** — broker min-notional ($10 crypto) is checked pre-submit; $5 cap correctly yielded "no broker-valid candidate"; $12 clears it. fee-adjusted qty delta recorded on close.
- Marketable limit: `limit_ioc_qty` recipe; stale quotes blocked.
- **Verdict:** cost model is sound and conservative.

## RISK CAGE
- **Four lanes separated:** real-money (always locked), standard paper entries, paper exploration, exits. Verified (`verify_trade_permission_read_model_separates_entries_exits`, `verify_paper_exploration_*`).
- **No bypass:** the only submit path is `PaperExecutionService → ExecutionCage → run_preflight → AlpacaAdapter`. Cage + preflight both enforce kill switch; the canonical `paper_exploration_guard` is shared so they cannot disagree (the PR #27 fix).
- Catastrophic kill switches respected (manual/max-drawdown/weekly/system-health block even exploration). Daily-drawdown is the only overridable switch, only for a marked paper probe, audited (`paper_exploration_kill_switch_override`).
- Duplicate orders prevented (`DUPLICATE_CLIENT_ORDER_ID`, broker-position same-symbol block, 1-position cap). Daily entry cap (3) enforced. Exits always allowed.
- Live promotion impossible without explicit operator action (`verify_live_flags_locked`, `verify_no_live_path_from_paper_exploration`).
- **Verdict:** the cage is the strongest part of Hive. No bypass found.

## EXIT LOGIC
- Stop / TP / trailing / invalidation / max-hold present (`dynamic_exit_levels`). Exit monitor uses broker truth; exits never blocked by kill switch.
- **Exit reason was inconsistent** across sources (max_hold_exit vs dynamic_stop_loss_hit vs null) — **fixed** by PR #30 canonical outcome (`canonical_exit_reason` + `raw_exit_trigger` preserved).
- Crypto fee-adjusted qty handled (`fee_adjusted_qty_delta`). Realized P/L agrees ledger↔outcome.
- **Partial fills:** ledger pairs FIFO and marks partial confidence; **not stress-tested** — flag for reset run.
- "Hold through small loss": implemented as noise tolerance **inside** stop/invalidation/max-hold — not hope. Acceptable.

## HEARTBEAT / LOOP LOGIC
- A research/learning scheduler + a paper autopilot cycle exist; the exploration lane is operator-triggered.
- **Gap:** the explicit **two-loop split is not clean** — a fast heartbeat that only updates quotes/positions/exits every candle, vs. a slower decision loop that gates new entries. Today new-entry gating and management are intermingled in the cycle.
- **Guardrail present:** `verify_heartbeat_does_not_force_entries` (planned PR B) + the adaptive-opportunity budget + cooldowns already prevent per-candle forced entries. The exploration daily cap (3) and 1-position cap prevent churn.
- **Action:** for the $200 run, configure the decision loop to gate entries (cooldowns, spread/regime), let the heartbeat manage exits only. Documented in reset plan.

## ASSET SCOPE
- Alpaca paper account: **crypto + US stocks/ETFs (fractional)** are the safe, supported, code-exercised classes. Options/forex/futures are **research-only** (no separate options risk engine; forex not verified on this account).
- Code classifies crypto vs stock and applies crypto min-notional ($10). **Recommendation:** reset run = **crypto + stocks only**; options/forex remain research-only.

## PROMOTION LOGIC
- Requires ≥20 closed exploration trades + positive after-cost expectancy + PF>1.10 + drawdown bound (`can_promote_from_exploration`). 20 is a **minimum**; 50 preferred (per mission). Slippage/spread/reconciliation-drift gates exist in the cage. Live stays locked.
- **Gap:** win/loss ratio + Sharpe/Sortino + explicit out-of-sample not yet in the promotion gate — add in backtest lab.

## VERDICT SUMMARY
- **Critical blockers (must hold before reset):** none new — the cage/preflight/live-lock are sound. The honest blocker to *value* (not safety) is **no proven edge yet**.
- **High-risk issues:** unproven strategy edge; two-loop heartbeat not cleanly separated; backtest lab thin (overfit/walk-forward not enforced).
- **Medium-risk:** partial-fill handling not stress-tested; duplicate cycle-trigger endpoints (clutter).
- **Safe cleanup:** duplicate cycle endpoints, stale fallback panels (see removal_candidates).
- **Strategy logic verdict:** mechanically safe and disciplined; **edge unproven**.
- **Asset-scope verdict:** crypto + stocks only; options/forex research-only.
- **Ready for $200 reset:** **YES** — to *generate evidence* (the plumbing is safe and correct). It is **not** ready to be called profitable.
- **Ready for live money:** **NO** — requires ≥50 closed trades with positive after-cost expectancy + PF>1.10 + bounded drawdown, none of which exists yet.
