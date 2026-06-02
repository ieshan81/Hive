# PHASE 2 — Endpoint Map (safety-prioritized)

The backend has **40+ routers** (`backend/app/routers/`). A full exhaustive map is large; this
audit prioritizes **order-capable, config-mutating, and live-relevant** endpoints — the ones that
matter for reset-readiness. Remaining routers (news, sentiment, social_reddit, market_data,
candle_lab, reports_hub, performance, scanners, etc.) are read/research-only display feeds.

## Alpha Factory (`/api/alpha-factory/*`, router `alpha_factory.py`)
| Path | Method | Auth | Mutating | Order? | Notes |
|---|---|---|---|---|---|
| `/status` | GET | public | no | no | read model status (+ session, exploration, failure breakdown) |
| `/scorecards` `/best-candidates` `/near-misses` `/session-summary` `/paper-exploration` `/memory-summary` `/research-runs` `/autonomous-status` | GET | public | no | no | read models |
| `/can-trade-paper` `/explain` | GET | public | no | no | read-only |
| `/run-exploration` | POST | **operator** | yes | **yes (cage)** | one tiny paper probe; AI-forbidden; never live |
| `/paper-exploration/set-cap` | POST | **operator** | yes (cap only) | no | bounded (0,$25]; AI-forbidden; live untouched |
| `/run-cycle` `/run-research-now` `/run-backtests` `/promote-candidates` `/consolidate-memory` `/parameter-sweep` `/walk-forward` | POST | **operator** | yes (DB) | no | research/promotion cycles; no broker orders |
| `/pause` `/resume` `/scheduler/*` | POST | **operator** | yes (scheduler) | no | scheduler control |
| `/cost-check` | POST | operator | no | no | deterministic cost calc |

## Paper settings (`/api/settings/paper-trading/*`, router `settings_paper.py`)
| Path | Method | Auth | Mutating | Notes |
|---|---|---|---|---|
| `/readiness` | GET | public | no | cockpit-truth readiness |
| `/set-drawdown-limit` | POST | **operator** | yes (`kill.daily_drawdown_pct` only) | AI-forbidden, confirmation phrase, bounded [0.25,10], live untouched, audited, no order |
| `/enable-orders` `/disable-orders` `/pause` `/resume` `/apply` | POST | **operator** | yes | paper-only toggles |
| `/dry-run` | POST | operator | no | no order |
| `/disable-all-paper-trading` | POST | **operator** | yes | safety stop |

## Live flags / danger (`live_flags.py`, `danger_zone.py`, `live_promotion.py`)
- Live-enable endpoints exist but are guarded by the live-lock architecture and operator gating; `verify_live_flags_locked` asserts they cannot flip live on without explicit multi-gate operator action. **Not exercised in this audit.**

## Autopilot / mission-control
- `GET /api/autopilot/decision-state` (router `api.py` alias + `autonomous_paper_learning.py`) — read-only; now surfaces exploration lane + last realized P/L.
- `GET /api/mission-control/status` — cockpit truth (4-lane permission via `_execution_safety`).

## Diagnostics
- `GET /api/alpha-factory/export-bundle` + `/download`, `/api/diagnostics/*` — read-only bundle (now includes `closed_trade_outcomes.json`).

## Findings
- **Every order-capable endpoint is operator-gated and AI-forbidden.** The only broker-submit path is `PaperExecutionService` via the cage.
- **Orphan/duplicate risk:** several near-duplicate cycle triggers exist (`/run-cycle`, `/run-autonomous-cycle`, `/run-one-cycle`, `/tick`, `/run-due`, `/supervised-burst`, `/start-fresh`, `/stop-after-tick`). These are research/scheduler controls (no broker orders) but are **clutter candidates** — see [removal_candidates.md](removal_candidates.md). Deferred (medium risk) pending a usage trace.
- **To verify in PR B:** `verify_every_ui_endpoint_has_backend_route.py` and `verify_no_dead_debug_routes_exposed.py` (planned).
