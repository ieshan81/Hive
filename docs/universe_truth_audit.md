# Universe / Radar Truth Audit

Date: 2026-06-02 · Run: `paper_validation_run_001`

Safety-critical: a false-zero Universe UI can make the operator take bad manual actions. This maps
every Universe UI field to its source and identifies the false-zero failure mode.

## Baseline truth (prod, Phase 0)
- `GET /api/universe/status` → **14.66 s** (frontend timeout ~4 s ⇒ fallback false-zero).
- Backend truth is **non-zero**: `total_symbols=20`, funnel `{available 20, cached 46, fresh 10, scored 18, eligible 3, shortlisted 3}`, blockers `{stale_bar 13, ALPHA_NOT_READY:no_alpha_scorecard 4, NEGATIVE_EDGE_AFTER_COST 1}`.
- `GET /api/universe/summary` and `/tiles` → **404** (no fast path existed).

## Field → source map

| UI field | Frontend source | Backend endpoint | Bundle file | Correct backend value | Current (broken) UI value | Failure mode |
|---|---|---|---|---|---|---|
| Available | Universe top card | `/api/universe/status` (slow) | `universe_summary.json` | 20 | 0 | slow `/status` times out → zero fallback |
| Cached | Universe top card | `/api/universe/status` | `universe_summary.json` | 46 | 0 | same timeout fallback |
| Fresh | Universe top card | `/api/universe/status` | `universe_summary.json` | 10 | 0 | same timeout fallback |
| Eligible | Universe top card | `/api/universe/execution-shortlist` / status funnel | `universe_execution_shortlist.json` | 3–4 | 0 | strict eligibility conflated into source; or timeout |
| Alpaca crypto API | Source proof | `/api/universe/sources` (live discovery, slow) | `universe_sources.json` | >0 (cached) | 0 | slow/empty source call shown as 0 instead of unknown |
| USD pairs | Source proof | `/api/universe/sources` | `universe_sources.json` | >0 | 0 | same |
| Execution shortlist | funnel/“To Trade” | `/api/universe/execution-shortlist` | `universe_execution_shortlist.json` | 4 (strict 0) | 0 | strict vs non-strict not distinguished |

## Root causes
1. **Slow `/api/universe/status`** (runs full `build_mission_control_status` ~15 s) vs ~4 s UI timeout → the UI's catch path renders **0** instead of "refreshing/unknown".
2. **No fast path** — top cards had nothing fast to read.
3. **Source vs eligibility conflation risk** — a strict `eligible=0` can be misread as "nothing in the universe", though the source universe is 20.
4. **Source proof shown as 0 when unknown** — a slow/empty cached Alpaca call rendered `0` rather than `null/unknown`.

## Fix (this branch)
- **Phase 2**: `GET /api/universe/summary` fast path — funnel + cached source proof only, never a fake 0 (unknown ⇒ null), explicitly separates `source_counts` / `display_counts` / `freshness_counts` / `funnel_counts`, surfaces `zero_eligible_explanation` + `source_nonzero_but_eligible_zero` + `status_latency_risk`.
- **Phase 3**: frontend top cards read the fast path; slow `/status` loads the detail table separately; unknown ⇒ grey/unknown not zero.
- **Phase 4**: count-semantics verifier (source never overwritten by eligible).
- **Phase 5**: universe truth in the latest diagnostic bundle + README_FIRST.

## Verifiers
- `verify_universe_truth_sources_are_consistent.py` (Phase 1)
- `verify_universe_summary_fast_path.py` (Phase 2)
- `verify_universe_counts_semantics.py` (Phase 4)
- `verify_universe_bundle_truth.py` (Phase 5)
