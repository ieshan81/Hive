# PHASE 2 — Frontend ↔ Backend Mapping (key trading pages)

Frontend: Next.js (`src/app/*`, `src/components/*`); API via `apiGet`/`apiPostOperator`. Mutating
calls go through the operator-token path. Full per-component sweep is PR D; this maps the
trading/safety-critical pages.

| Page / component | Primary endpoint(s) | Mutating? | Token? | UI truth source |
|---|---|---|---|---|
| Cockpit (`CockpitDashboard.tsx`) | `GET /api/mission-control/status` (25s poll) | no | no | `_execution_safety` 4-lane + `alpha_factory` block (incl. paper_exploration) |
| Cockpit readiness button | `POST /api/execution/paper/readiness-check` | no (check) | operator | readiness service |
| Alpha Factory panel | `GET /api/alpha-factory/{status,scorecards,near-misses,best-candidates,session-summary,paper-exploration}` | no | no | AlphaResearchReadModelService |
| Paper exploration controls (planned PR D) | `POST /api/alpha-factory/{run-exploration,paper-exploration/set-cap}` | yes | operator | PaperExplorationService |
| Settings (paper) | `GET /api/settings/paper-trading/readiness`; `POST .../set-drawdown-limit,enable-orders,...` | yes | operator | PaperSettingsService |
| Mission Control | `GET /api/mission-control/status` | no | no | MissionControlReadModel |
| Hive Memory / Brain | `GET /api/alpha-factory/memory-summary`, memory endpoints | no | no | MemoryEvidenceConsolidatorV2 |
| Decision state (autopilot) | `GET /api/autopilot/decision-state` | no | no | AutopilotDecisionStateService (+ exploration + last realized P/L) |
| **Hive Engine Map (PLANNED PR D)** | `GET /api/hive-engine-map` | no | no | aggregate read model across lifecycle nodes |

## Findings
- Every safety-critical page maps to a real read model; labels match backend truth (post cockpit fixes).
- Mutating buttons are operator-gated; AI actor forbidden server-side.
- **Gap:** no in-UI paper-controls panel yet (curl-only) and no engine-map tab — both **PR D**.
- **To verify (PR B):** `verify_every_ui_endpoint_has_backend_route.py` (no UI calls a missing route) + `verify_no_dead_debug_routes_exposed.py`.
