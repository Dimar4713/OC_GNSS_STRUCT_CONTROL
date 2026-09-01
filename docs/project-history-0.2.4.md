# Engineering Preview 0.2.4 — project change history

Status: Windows engineering-evaluation package accepted on exact-head CI and merged to `main`; post-acceptance runtime fixes remain evidence-gated.

This document is the repository-side chronology for the 0.2.4 functional increment. It records merged engineering slices, authority boundaries, package-level evidence, and post-acceptance runtime corrections.

## Baseline

- Stable predecessor packaging baseline: Engineering Preview 0.2.3.
- 0.2.4 objective: engineer-facing constellation digital-twin input, perturbation, operational-resource state, lineage, physically consistent continuation, reviewed GNSS/NORAD intake, and a consolidated Windows operator package without weakening Orekit/DSST authority.
- Source scenarios remain immutable in all derived-scenario flows.

## Merged change history

| PR | Result | Engineering increment |
|---|---|---|
| #121 | merged | Backward-compatible digital-twin domain primitives: operational spacecraft state, groups, perturbation metadata and scenario lineage. |
| #122 | merged | XLS/XLSX spacecraft-state import including legacy `.xls`, current mass/fuel and optional propulsion/correction metadata. |
| #123 | merged | Packaged operator workbook validation/preview flow. |
| #124 | merged | Workbook import promoted only into a new derived scenario with parent id/hash lineage and no-overwrite protection. |
| #125 | merged | Walker Delta constellation generator core. |
| #126 | merged | Walker generator wired into packaged operator UI with preview/create derived scenario flow. |
| #127 | merged | Authoritative Orekit 13.1.7 DSST osculating-to-mean conversion endpoint and fail-closed Python client. |
| #128 | merged | Per-satellite osculating Keplerian operator flow: authoritative preview then immutable derived scenario. |
| #129 | merged | Deterministic perturbation designer core/UI with explicit distribution parameters, deterministic seed, sampled deltas and precedence satellite > group > plane > constellation. |
| #130 | merged | Catalog-driven perturbation targets for spacecraft, planes and groups; stale/free-text target IDs removed. |
| #131 | merged | Operational maneuver propellant preflight with sequential mass/fuel accounting and per-spacecraft Isp authority. |
| #132 | merged | Operational mass/fuel/Isp integrated into `run_scenario`; insufficient fuel fails closed before backend invocation. |
| #133 | merged | Immutable operational resource snapshots and packaged current-mass/fuel history table. |
| #134 | merged | Physically consistent propagated runnable child scenarios using final `PropagationResult` plus final operational resource state. |
| #135 | merged | Fail-closed completed-run promotion core requiring exact manifest, normalized scenario, propagation result and resource evidence. |
| #136 | merged | Completed-run promotion wired into packaged UI; successful runs persist exact `propagation_result.json`. |
| #137 | merged | Explicit Walker/osculating engineering inputs; hidden orbital defaults removed, with singularity and blank-input guards. |
| #138 | merged | Typed canonical perturbation parameter registry, domain-level unit checks and stricter target-scope invariants. |
| #140 | merged | Perturbation Designer requires explicit scope for every enabled rule; no implicit whole-constellation scope. |
| #141 | merged | Strict TLE and OMM JSON validation/normalization with source SHA-256 provenance; runnable promotion initially blocked. |
| #142 | merged | Orekit TLE SGP4/SDP4 TEME authority to osculating PV and force-model-consistent DSST mean. |
| #143 | merged | Consolidated TLE authority flow and immutable derived-scenario creation with NORAD provenance. |
| #144 | merged | TLE authority extended to explicit target epoch/time scale before DSST conversion. |
| #145 | merged | Strict preview-only GPS YUMA, GPS SEM and labelled GLONASS interchange intake with source provenance and fail-closed semantics. |
| #146 | merged | Explicit propulsion/correction catalog validation; catalog metadata never overrides operational mass/fuel/thrust/Isp authority. |
| #147 | merged | Reviewed GPS YUMA/SEM Orekit GNSS analytical propagation authority to target epoch, inertial PV and DSST mean. |
| #148 | merged | GPS almanac operator authority preview and immutable derived-scenario creation with typed lineage. |
| #149 | merged | Dedicated GLONASS authority using explicit semantics, Orekit `GLONASSAlmanac`/`GLONASSAnalyticalPropagator`, then DSST mean. |
| #150 | merged | Strict GLONASS authority-source preview and immutable derived-scenario creation; legacy reduced-precision records remain non-promotable. |
| #151 | merged | Backward-compatible structural lineage integrity contract with `integrity_version: 1` for real 64-hex parent SHA-256 hashes. |
| #152 | merged | **Windows package acceptance for Engineering Preview 0.2.4.** Versioning synchronized to 0.2.4; package stages the consolidated operator surface; packaged legacy `preview/app.py` is excluded; shared base shell is internalized as `base_preview_shell.py`; package lock includes workbook dependencies; CLI routes to `consolidated_release_app`; real clean-Windows packaged launch reaches `/health=0.2.4` and verifies pinned Orekit 13.1.7 data revision/SHA. |
| #153 | merged | **GLONASS almanac Python→Java contract fix.** Real operator testing exposed HTTP 500 because the Python client sent `delta_i_rad`, `delta_t_s`, `delta_t_dot` while the Java sidecar contract is `delta_irad`, `delta_ts`, `delta_tdot`. The client now sends the exact sidecar field names and a regression test locks the request contract. Numerical GLONASS/Orekit/DSST authority semantics are unchanged. |

## Current authority boundaries

1. Screening is not design/validation authority.
2. High-fidelity osculating-to-mean conversion is Orekit/DSST-only and fails closed if authority/fingerprints mismatch.
3. Perturbations act on the canonical mean-element representation and never silently reinterpret osculating inputs.
4. NORAD TLE reaches canonical MeanOrbit only through `TLE -> Orekit SGP4/SDP4 TEME@target epoch -> osculating PV -> selected inertial frame -> Orekit DSST mean`.
5. OMM remains non-promotable until its own reviewed Orekit conversion boundary exists.
6. GPS YUMA/SEM reaches canonical MeanOrbit only through Orekit parser + GNSS analytical propagator at explicit target epoch + inertial PV + DSST mean.
7. GLONASS uses a separate reviewed authority: explicit authority-ready semantics -> Orekit `GLONASSAlmanac` -> `GLONASSAnalyticalPropagator` -> target-epoch inertial PV -> DSST mean. Legacy `draconian_period_s` is never reinterpreted as `deltaT`.
8. Derived GPS/GLONASS/TLE scenarios preserve source filename/SHA/record identity/authority and never overwrite parent or existing target YAML.
9. Lineage integrity v1 is a structural SHA-256 claim; historical unversioned lineage remains readable.
10. Maneuver resource accounting is coupled preflight/ledger evidence and does not replace Orekit impulse physics.
11. Propulsion/correction catalog data is validation/reference metadata only; operational numerical authority remains explicit scenario/resource state.
12. A runnable continuation scenario requires complete persisted propagation evidence reaching the exact scenario horizon.
13. Historical runs without persisted `propagation_result.json` remain non-promotable without rerun.
14. The distributable Windows Preview 0.2.4 package must route through `consolidated_release_app`, exclude the legacy public `preview/app.py`, and attest pinned Orekit revision/SHA at runtime.

## Accepted Windows package evidence — PR #152

- PR #152 exact head: `b7fd0f036410a19a8592906372e72817ce8a9a03`.
- Exact-head required workflows all terminal success:
  - `ci` run `33432186311` — GREEN;
  - `preview-package-compat` run `33432186367` — GREEN;
  - `preview-0.2-package` run `33432186417` — GREEN.
- `windows-preview-024-smoke` job `99620125282` — GREEN.
- Real packaged clean-Windows acceptance step — GREEN.
- Artifact: `engineering-preview-python-0.2.4-win10`, artifact id `9773032400`.
- Artifact digest: `sha256:96fa876c2cf30dffd46e4ef772ad50499bf067dd19b528f67ee060dfa13e7be8`.
- Artifact retention expiry: 2026-09-14.
- PR #152 merge commit: `25f704d35833664fda8f183501f6e8e49422da8a`.
- Runtime acceptance proves Preview `/health` reports `0.2.4` and the packaged Orekit sidecar reports Orekit `13.1.7` with the pinned reviewed data revision and physical SHA-256.

## Accepted post-acceptance correction evidence — PR #153

- PR #153 exact head: `b31bf7d60ff545dfca5b0458beb912aaed6d331a`.
- Exact-head required workflows all terminal success:
  - `ci` run `33474303934` — GREEN;
  - `preview-package-compat` run `33474304042` — GREEN;
  - `preview-0.2-package` run `33474303969` — GREEN.
- Replacement Windows artifact: `engineering-preview-python-0.2.4-win10`, artifact id `9787611406`.
- Replacement artifact digest: `sha256:aa6e8ab6e870f22fba6d324f3555ad93b9ef8b1e4cbece6222dc7341619f7959`.
- Replacement artifact retention expiry: 2026-09-15.
- PR #153 merge commit: `60ef46a2c60079b1e99aa79e2b1e8ea2ae448022`.
- This artifact supersedes artifact `9773032400` for GLONASS almanac testing because it contains the corrected Python→Java request contract.

## Next incomplete work

1. Retest the real GLONASS authority flow with the operator-provided `glonass-labelled-authority-v1` fixture against the #153 replacement package.
2. Continue remaining authority hardening separately: OMM authoritative conversion, GPS/GLONASS raw-source SHA attestation through sidecar, GPS week ambiguity handling, and exact returned target-epoch verification where applicable.

## Maintenance rule

Every subsequent engineering PR must update this history with the PR number, functional delta, authority boundary where relevant, and exact evidence checkpoint after merge when known.
