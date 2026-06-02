# PHASE 13 — Reset-to-$200 Plan

Claude **cannot** reset the Alpaca account or paper keys — the user does that manually. This is the
exact, safe procedure + validation run definition.

## Pre-reset (operator, mostly already true — see safety_freeze_report)
1. **Disable schedulers** if you want a clean start (`POST /api/alpha-factory/scheduler/pause`, operator token). Optional — exploration is operator-triggered anyway.
2. **No open positions** — confirmed `open_positions_count = 0`.
3. **No active orders** — confirmed `active_orders_count = 0`.
4. **Archive current diagnostic bundle** — `GET /api/alpha-factory/export-bundle` (save the file).
5. **Archive/reset noisy memory** — PR C (export → archive noisy active lessons; preserve closed-trade evidence). Not a blocker; memory is advisory-only.
6. **Confirm core history preserved** — orders / trades / outcomes / execution_logs / config_history / audit remain (never deleted).

## Reset (user, manual)
7. Reset Alpaca paper account/keys to **$200** (Alpaca dashboard or new paper keys).
8. Update Railway secrets if keys changed (`ALPACA_*`). Do not commit secrets.
9. Confirm broker equity/buying power ≈ **$200** (`GET /api/mission-control/status`).

## Validation run config (`paper_validation_run_001`)
- **live disabled** (`live_orders_enabled=false`, live_trading_locked) — do NOT change.
- paper enabled · exits enabled · standard entries controlled.
- paper exploration cap **$12** (ceiling $25; never silent raise) — `POST /api/alpha-factory/paper-exploration/set-cap {cap_usd:12}` (operator).
- max single exploration notional ≤ **$25** · **max positions 1** · **max entries/day 3**.
- heartbeat observes every cycle but **does not force entries**; slower decision loop gates new entries (cooldown + spread/regime).
- **crypto + stocks only** (supported/safe). options/forex **research-only**.
- paper daily drawdown limit 5.0 (already set; bounded ≤10) if you want standard entries unpaused.

## Run target
- **minimum 20** closed trades · **preferred 50**.

## Evaluate (after the run)
after-cost expectancy · profit factor · win rate · avg win/loss · max drawdown · slippage/spread ·
duplicate prevention · exit quality · memory lessons · broker reconciliation · UI truth · diagnostic truth.

## Stop conditions (halt the run immediately)
duplicate/runaway order · live path accidentally available · reconciliation drift · missing exit plan ·
repeated stale-quote submit attempts · uncontrolled drawdown · memory directly changing trades ·
negative expectancy after enough sample · failed diagnostics.

## Promotion gate (after ≥50 clean trades)
positive after-cost expectancy + PF>1.10 + bounded drawdown + clean reconciliation → *still*
operator-gated tiny-live. **Not** automatic.
