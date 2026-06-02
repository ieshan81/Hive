# PHASE 0 — Safety Freeze Report

Generated during the forensic audit (read-only). No orders submitted, no `dry_run:false`, no
config mutated, no live trading touched. All values below are from read-only production endpoints
and local git checks.

Prod base: `https://hive-production-7343.up.railway.app`

## 1–17. Verified state

| # | Check | Value | Safe? |
|---|-------|-------|-------|
| 1 | Live trading locked | `live_trading_locked = true` | ✅ |
| 2 | `live_orders_enabled` | `false` | ✅ |
| 3 | Alpaca broker mode | paper (`broker_connected = true`, paper-api) | ✅ |
| 4 | `.env` gitignored & untracked | gitignored; `git ls-files` shows no tracked `.env` | ✅ |
| 5 | No secrets tracked | only `.env.example` templates tracked | ✅ |
| 6 | No repeated auto exploration submits | `exploration_entries_today = 1`, lane operator-triggered only (no scheduler drives submit) | ✅ |
| 7 | Open positions | `open_positions_count = 0` (positions endpoint count 0) | ✅ broker flat |
| 8 | Active orders | `active_orders_count = 0` | ✅ |
| 9 | Config version | active (cost model `v2_components_no_double_count`) | ✅ |
| 10 | Latest closed trade | last_exit `DOGE/USD`, reason `position_closed`, realized P/L `+0.166667`; ledger gross since reset `-1.6928` | ✅ recorded |
| 11 | Latest paper exploration | `enabled = true`, `allowed = true`, `open_position = false`, cap `$12` | ✅ |
| 12 | Paper learning | `paper_learning_on = true`, `scheduler_enabled = true` | ✅ |
| 13 | Standard paper entries | `new_entries_allowed = true` (unpaused after operator drawdown→5.0) | ✅ controlled |
| 14 | Paper exploration | `paper_exploration_allowed = true` | ✅ |
| 15 | Exits | `exits_allowed = true` | ✅ |
| 16 | Scheduler | enabled (research/learning); does NOT auto-submit exploration probes | ✅ |
| 17 | Diagnostic bundle truth | trades_history ↔ paper_experiment_outcomes unified (PR #30); broker flat confirmed | ✅ |

## Git / secret checks
- `git status` — clean working tree on audit branch.
- `git ls-files | grep .env` — **none tracked** (only `.env.example`).
- `.env` — gitignored.
- Operator token — present only in `backend/.env` (`OPERATOR_SECRET`), loaded via `settings.operator_secret`; never printed or committed.

## Acceptance
- **Live money locked** — confirmed (live_orders off, broker paper, live_trading_locked true).
- **No accidental order submission** — broker flat (0 positions, 0 active orders); exploration is operator-triggered only.
- **Safe audit state documented** — yes. The system is in a clean, flat, paper-only state suitable for a forensic audit and a subsequent $200 reset.

## Audit ground rules followed
Read-only endpoints only · no `dry_run:false` · no new orders · no config mutation · no live path touched · no secrets printed.
