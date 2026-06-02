# PHASE 3 — UI Visual Audit

Scope note: a deep computer-vision pass over every deployed page is a **PR D** task (engine-map tab
+ screenshots). This document records the UI findings already established + the audit checklist.
Screenshots will be attached under `docs/audit/screenshots/` in PR D.

## Findings already fixed (prior PRs, verified)
| Page | Issue | Fix | Status |
|---|---|---|---|
| Cockpit | Cramped `max-w-6xl`, dead right-side space | widened to `max-w-[1500px] mx-auto`, responsive padding | ✅ live |
| Cockpit | Confusing "Bot can trade: NO" conflated entries/exits | relabeled: Paper Learning / Standard Paper Entries / Paper Exploration (READY/BLOCKED) / Exits (ACTIVE/BLOCKED) / Real Money (LOCKED) / Alpaca | ✅ live |
| Cockpit | No exploration truth | added Trade Permission panel + exploration candidate + broker-validity line | ✅ live |
| Cockpit | Stale entries/exits summary | drawdown-aware summary ("Standard entries paused by daily drawdown; paper exploration remains available") | ✅ live |

## Outstanding UI checklist (PR D — per page: Mission Control, Cockpit, Alpha Factory, Hive Memory, Engine/Brain, Settings)
For each: screenshot · centered? · right-side dead space? · missing data panels · raw-JSON dumps · duplicate cards · confusing labels · dead buttons · stale values · UI-vs-backend contradiction · spinners/timeouts · trader usefulness. Each issue → severity · page · screenshot path · symptom · backend source · fix.

## UI principles (enforced going forward)
- No raw JSON as primary UX.
- No excessive sci-fi; simple flow/engine map preferred.
- Every panel maps to a backend truth source (see frontend_backend_mapping).
- Mobile responsive; no horizontal scroll.

## Verdict
Cockpit core truth + layout are professional and correct (post prior PRs). A full per-page CV sweep
+ the **Hive Engine Map** tab (read-only `/api/hive-engine-map`) are the remaining UI deliverables (PR D).
This is **not a reset blocker**.
