# PHASE 4 — Removal Candidates (evidence-based)

Deletion is evidence-based. **Delete low-risk clutter now; defer medium/high-risk** pending a usage
trace + tests. This PR A is docs-only — actual deletions land in **PR B** with tests.

## Never remove (safety/evidence)
live lock · kill switches · risk cage · preflight · broker reconciliation · ConfigHistory ·
audit logs · diagnostic evidence · exit monitor · OrderRecord · TradeRecord · PaperExperimentOutcome ·
memory tied to closed trades.

## Candidates
| Item | Why | Evidence | Risk | Decision |
|---|---|---|---|---|
| Duplicate cycle-trigger endpoints (`/run-cycle` vs `/run-autonomous-cycle` vs `/run-one-cycle` vs `/tick` vs `/run-due` vs `/supervised-burst`) | Several near-identical research/scheduler triggers | endpoint_map enumeration | **Medium** (some may be wired to UI) | **Defer** — need `verify_every_ui_endpoint_has_backend_route` usage trace first |
| Stale fallback panels / raw-JSON dumps in older tabs | UX clutter; contradict canonical truth | UI audit (PHASE 3) | Low–Med | **Defer to PR B** with screenshot evidence per page |
| Old/abandoned verifiers (if any superseded) | Maintenance noise | needs `git`/usage scan | Low | **Defer** — confirm not in CI before removal |
| Commented dead code / unused imports | Clutter | per-file lint | Low | **Delete in PR B** after `npm run lint` + compileall |
| Old blocked-trade artifacts confusing "latest cycle" truth | Can mislead decision-state | decision-state already prefers ledger/canonical | Med | **Defer** — verify decision-state truth first |
| `verify_*` duplicates around exploration (e.g., overlapping never-500 vs no-mismatch) | Some overlap | both pass; complementary | Low | **Keep** (different invariants) |

## Process for PR B
1. Add `verify_every_ui_endpoint_has_backend_route.py` + `verify_no_dead_debug_routes_exposed.py`.
2. Trace each candidate's references (frontend `apiGet/apiPost`, router includes).
3. Delete only proven-dead low-risk items; run `compileall` + `test:api` + `build` + verifier battery.
4. Record removed files in FINAL_AUDIT_REPORT.

**Nothing deleted in this PR A.** All removals require the usage trace + green tests first.

---

## PR B executed (evidence-based removal + guard verifiers)
**Verifiers added & passing:**
- `verify_every_ui_endpoint_has_backend_route.py` — **90 UI endpoints, all route to a real backend route** (zero dead frontend calls).
- `verify_no_dead_debug_routes_exposed.py` — **no public mutating debug/raw/eval routes** (segment-boundary match).

**Removed (proven dead — 0 references backend-wide incl. `worker.py`, verified by static + string + dynamic scan):**
- `backend/app/services/position_sizing.py` (108 lines; `SizeResult` unused — sizing now via MicroCapAllocator/cage).
- `backend/app/services/session_scheduler.py` (281 lines; `RateLimitBucket` unused — sessions via MarketSessionService, scheduling via autonomous schedulers).

**Kept (NOT dead):**
- `backend/app/services/cycle_engine.py` — imported by `backend/worker.py` (`CycleEngine`); the orphan scan initially missed the worker entrypoint. **Live; not removed.**

**Deferred (still medium-risk, operator-triggered via curl — not frontend-dead):**
- Duplicate cycle endpoints (`/run-cycle` etc.) — operator endpoints; "no frontend caller" ≠ dead. Defer.

**Outcome:** route + module hygiene is otherwise clean; no further low-risk proven-dead code found. Post-removal: app + `worker.py` compile, 8/8 verifier battery, `test:api`, `build` all green.
