# PHASE 7 — Backtesting / Strategy Lab Plan

Hive must **test** hypotheses, not invent strategies from vibes. Design a realistic lab (do not
overbuild). Existing: `ResearchBacktestRun`, `ResearchLabService`, parameter-sweep + walk-forward
endpoints exist but are thin and not enforced as a promotion gate.

## Target lab capabilities
- Hypothesis input (typed: symbol set, asset class, timeframe, entry/exit rules, params).
- Candle data fetch (stored `HistoricalBar`; extend coverage as needed).
- Multi-timeframe + session splits + asset-class splits.
- Cost/slippage/fee model (reuse v2 `research_cost_model`) + min-notional model.
- Train/test split + **out-of-sample** + **walk-forward** validation.
- Parameter sensitivity + **overfit warning** (e.g., in-sample vs out-of-sample degradation, param-cliff detection).
- Result storage + promotion recommendation + rejection reason.

## Reference patterns (concept only — see reference_architecture_review)
- **VectorBT**: vectorized param grids + cost sensitivity (fast sweeps).
- **Freqtrade hyperopt + protections**: bounded search; cooldown/low-profit protections.
- **Backtrader analyzers**: Sharpe/Sortino/drawdown/trade-list metrics.
- **LEAN**: alpha-model vs execution-model separation so signals are testable independent of execution.

## BacktestResult schema (target — extend `ResearchBacktestRun`)
strategy_id · version · parameter_set · assets_tested · timeframe · period · sample_size ·
num_trades · win_rate · avg_win · avg_loss · expectancy · profit_factor · sharpe · sortino ·
max_drawdown · fees/slippage assumptions · **overfit_risk** · **out_of_sample_result** ·
recommended_paper_allocation · rejection_reason.

## Promotion linkage (the key gate — enforce in PR C/E)
`verify_backtest_result_required_before_paper_candidate.py`: a hypothesis cannot become a paper
candidate without a stored BacktestResult that passed out-of-sample + min sample. Backtest-only
strategies can **never** go live.

## Phasing (do not overbuild)
- **Now (documented):** schema + gate design; reuse existing research backtests.
- **PR (later):** wire out-of-sample/walk-forward + overfit warning into the promotion gate; add VectorBT-style sweep as an optional fast lane (original implementation, no copied code).

## Acceptance (target)
AI proposes hypotheses → lab tests them → only tested hypotheses enter paper exploration →
no backtest-only strategy goes live.
