# Goal: FINAL REAL MONEY PASS — Shadow observation floor

**Status:** active

## Outcome

Shadow League must produce measurable learning evidence every tick: diagnostics prove push-pull setups reach the shadow observer; if `shadow_count=0`, exact measurable reasons and near-misses are exposed (not vague text); L0 observations allowed for alpha-blocked setups when quality ≥ observation_floor; bundle includes shadow diagnostics with no shadow timeout; live locked, paper mode, 0 broker attempts.

## Verification

- All scripts: `verify_push_pull_calls_shadow_observer.py`, `verify_l0_observation_created_before_alpha_gate.py`, `verify_shadow_floor_diagnostics_present.py`, `verify_no_silent_shadow_skip.py`, `verify_shadow_never_submits_broker.py`, `verify_latest_bundle_shadow_diagnostics.py`
- Full local battery + `npm run test:api` + `npm run build`
- Prod smoke: runtime/summary, shadow-league/status, productivity, bundle download (section_errors=[], shadow diagnostics present)

## Constraints

- Do NOT enable live, submit broker orders, force paper trades, loosen risk/preflight/cage/alpha gates, enable stock broker trades, run rebuild, delete validation history, or fake shadow rows.
- Do NOT lower floors blindly; fix scoring/floor calibration only if evidence shows scale mismatch.

## Boundaries

- `backend/app/services/push_pull_scan_service.py`, shadow services, scheduler, shadow-league status API, diagnostic bundle, verifiers only.

## Iteration policy

Run failing verifier → read tick/shadow path → add diagnostics or fix feed/calibration → rerun verifier → full battery.

## Blocked stop

After 3 consecutive turns with same external blocker (no deploy access, prod unreachable), report paths tried and unlock needed.
