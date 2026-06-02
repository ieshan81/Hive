# PHASE 9 — Strategy Viability Review

Blunt answers. No profit claims.

1. **Worth building vs Freqtrade/3Commas/WunderTrading/QuantConnect?** Only if Hive's *unique* value lands: an **evidence-gated self-correction brain + caged paper-exploration lane** that refuses to trade without proven after-cost edge. As a generic bot it is behind Freqtrade/LEAN. As a *disciplined truth-and-learning machine* it has a defensible niche. Verdict: continue, but the value is the discipline, not the strategies.
2. **Hive's unique edge:** the cage + canonical outcome truth + near-miss/exploration evidence ladder + (planned) typed memory brain. Strong **safety/truth** engineering; **no trading edge proven yet.**
3. **Still unproven:** any positive after-cost edge; backtest rigor (overfit/walk-forward); the two-loop heartbeat; the typed memory pipeline.
4. **What would kill the project:** chasing features instead of evidence; letting AI memory drive trades; overfitting on tiny samples; calling it "ready for live" without ≥50 clean trades.
5. **Evidence required before live:** ≥50 closed paper trades, positive after-cost expectancy, PF>1.10, bounded max drawdown, clean reconciliation, no duplicate/runaway, consistent exits — then *still* operator-gated tiny-live.
6. **Candle-by-candle heartbeat for $200?** Heartbeat for **management/observation** yes; forcing an **entry** every candle, no. Entries must be gated by setup quality + cooldowns.
7. **Timeframes too noisy:** sub-5m for a $200 account (fees/spread dominate). Prefer 15m–1h for entries; 1h/4h longer-horizon family already added.
8. **Cadence to reduce churn:** heartbeat each cycle (manage exits/quotes); new entries gated by cooldown + spread/regime + ≤3 exploration entries/day + 1 position.
9. **Start with:** **crypto + stocks** (both supported/safe). Crypto gives 24/7 sample velocity; stocks add regime diversity. Keep separate risk treatment.
10. **Options/forex:** **research-only** until a dedicated risk engine / account verification exists.
11. **Exact validation run after reset:** `paper_validation_run_001` — $200, live disabled, exploration cap $12 (≤$25), 1 position, ≤3 entries/day, crypto+stocks, heartbeat manages / decision loop gates entries; run to **20 (min) → 50 (preferred)** closed trades; evaluate after-cost expectancy/PF/drawdown/slippage/exit-quality/reconciliation/UI-truth.
12. **Current confidence level:** **Level 1 → early Level 2.**

## Confidence ladder (current placement)
- L0 broken plumbing — **passed**.
- L1 trades paper end-to-end — **✅ proven** (real BTC probe filled + exited + canonical outcome).
- L2 clean outcomes/memory/diagnostics — **partial** (outcomes ✅ unified PR #30; memory ⚠️ advisory-only, not yet typed pipeline; diagnostics ✅).
- L3 20 closed paper trades, controlled risk — **not yet** (handful of closed trades).
- L4 50+ closed trades, positive after-cost expectancy — **not yet**.
- L5 tiny-live eligible, operator-gated — **NO**.

**Audit confidence level: 1 (early 2).** Do not claim L5.
