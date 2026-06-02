# PHASE 1 — Reference Architecture Review

Patterns studied from public docs/architecture. **No proprietary or licensed source code was
copied.** Only design *concepts* are adapted; all Hive implementation is original.

## Licensing note
- Freqtrade (GPLv3), Backtrader (GPLv3), VectorBT (open core; PRO is commercial), QuantConnect/LEAN (Apache-2.0 core). **Do not paste GPL code into Hive** (would impose GPL). Concepts/architecture ideas are not copyrightable; original implementations are safe. 3Commas/WunderTrading are closed SaaS — UI/UX *ideas* only.

## Ideas worth adapting (concept only)
| Source | Concept to adapt | How Hive applies it |
|---|---|---|
| Freqtrade | Strategy = class with explicit `populate_entry/exit` + ROI/stoploss/trailing config; dry-run mode; **protections** (cooldown, max-drawdown, low-profit pairs); pairlist/volume filters; hyperopt | Hive already has cooldowns, kill switch, near-miss gating. Adopt: typed strategy config object + protections registry + hyperopt-style param sweep in the backtest lab |
| VectorBT | Vectorized **fast parameter sweeps**, many variants, cost/slippage sensitivity, session/regime slicing | Backtest lab should run param grids + session splits + cost-sensitivity per hypothesis (see backtesting_lab_plan) |
| QuantConnect/LEAN | Modular **alpha → portfolio → risk → execution** model separation; universe selection; security abstraction | Hive's cage already separates execution/risk; adopt explicit *alpha-model vs execution-model* boundary so signals are testable independent of execution |
| Backtrader | Simple event-driven backtest lifecycle + **analyzers** (Sharpe, drawdown, trade list) | Backtest result schema should store analyzer-style metrics (already designed in lab plan) |
| 3Commas / WunderTrading | Bot **control panel** UX, paper/demo workflow, clear safety toggles, strategy templates | Engine-map tab + paper-controls panel (PR D) should mirror this clarity; no sci-fi, no raw JSON |
| Alpaca docs | Broker order types, crypto 24/7, fractional shares, **paper reset is manual**, min-notional | Confirmed: crypto + fractional stocks supported; min-notional enforced; reset is user-manual (PHASE 13) |

## Things NOT suitable / too complex for now
| Item | Why avoid (for now) |
|---|---|
| Full LEAN engine adoption | Massive; would replace Hive's whole stack. Borrow patterns only. |
| Freqtrade hyperopt at scale | Overfit risk on a $200 account; start with small bounded sweeps + out-of-sample. |
| Options/forex/futures strategies | No separate options risk engine; forex unverified on account. Research-only. |
| Copying any strategy code | License + edge-not-transferable + overfit risk. |
| Heavy multi-exchange abstraction | Hive is Alpaca-only; don't build exchange abstraction yet. |
| Social/copy-trading (3Commas-style) | Out of scope; no edge for a disciplined testing machine. |

## Alpaca account capability (verified via code + docs)
- **Crypto:** supported, 24/7, min-notional ~$10, fractional. ✅ exercised.
- **US stocks/ETFs:** supported, fractional. ✅ (research/exit code present).
- **Options:** Alpaca supports options, but Hive has **no options risk engine** → **research-only**.
- **Forex/Futures:** not verified on this account → **research-only**.
- **Paper reset:** manual by the user (Alpaca dashboard / new keys). Claude cannot reset it.

## Takeaway
Adopt: typed strategy + protections registry, a real backtest lab with out-of-sample/walk-forward,
alpha-vs-execution separation, and a clean control-panel UI. Avoid: wholesale engine replacement,
unbounded hyperopt, unsupported asset classes, and any code copying.
