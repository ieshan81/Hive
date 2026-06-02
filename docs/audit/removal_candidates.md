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
