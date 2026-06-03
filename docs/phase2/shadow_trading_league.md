# Phase 2 — Shadow Trading League

Learning-only virtual trades. **No broker orders**, no live trading, no `dry_run:false`.

## Promotion ladder

| Level | Name | Meaning |
|------:|------|---------|
| 0 | `observed_setup` | Push-pull setup scored and recorded |
| 1 | `shadow_trade` | Virtual open trade (paper blocked) |
| 2 | `shadow_proven_setup` | Enough closed shadow wins |
| 3 | `paper_candidate` | Shadow-eligible for paper **review** — still requires alpha + cage + operator gates |

Level 3 does **not** bypass broker paper submission.

## Services

- `shadow_trade_service.py` — create observations/trades from push-pull
- `shadow_outcome_service.py` — simulated closes (reference prices only)
- `shadow_promotion_ladder_service.py` — L0→L3 promotions
- `shadow_league_bundle_service.py` — diagnostic bundle sections

## Config (`default_config.shadow_league`)

Enabled by default; stock shadow allowed with `data_quality` flags when bars are stale.

## Verifiers

- `verify_shadow_trade_never_submits_broker.py`
- `verify_stock_stale_creates_shadow_not_paper.py`
- `verify_shadow_outcomes_not_broker_evidence.py`
- `verify_no_observed_to_broker_paper_jump.py`
- `verify_shadow_league_bundle_sections.py`
- `verify_shadow_league_preserves_validation_run.py`

## API

`GET /api/shadow-league/status` — minimal cockpit panel.

## Bundle (latest mode)

- `shadow_trades_summary.json`
- `shadow_outcomes.json`
- `strategy_promotion_ladder.json`
- `why_no_trade.json`
