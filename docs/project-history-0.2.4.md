# Engineering Preview 0.2.4 — project change history

Status: active development line built on the stable Preview 0.2.3 packaging baseline.

This document is the repository-side chronology for the 0.2.4 functional increment. It records merged engineering slices, their authority boundaries, and the next incomplete work. It is not a release claim: Windows package acceptance remains a separate evidence gate.

## Baseline

- Stable packaging baseline: Engineering Preview 0.2.3.
- 0.2.4 objective: engineer-facing constellation digital-twin input, perturbation, operational-resource state, lineage, and physically consistent continuation without weakening Orekit/DSST authority.
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
| #129 | merged | Deterministic perturbation designer core/UI: explicit M, Gaussian sigma or Uniform bounds, deterministic seed, actual sampled deltas and precedence satellite > group > plane > constellation. |
| #130 | merged | Catalog-driven perturbation targets for spacecraft, planes and groups; stale/free-text target IDs removed. |
| #131 | merged | Operational maneuver propellant preflight core with sequential mass/fuel accounting and per-spacecraft Isp authority. |
| #132 | merged | Operational mass/fuel/Isp integrated into run_scenario before propagation; insufficient fuel fails closed before backend invocation. |
| #133 | merged | Immutable operational resource snapshots and packaged current-mass/fuel history table. |
| #134 | merged | Physically consistent propagated runnable child scenarios using the actual final PropagationResult plus final operational resource state. |
| #135 | merged | Fail-closed completed-run promotion core requiring exact manifest, normalized scenario, propagation result and resource evidence. |
| #136 | merged | Completed-run promotion wired into packaged operator UI; successful runs persist exact `propagation_result.json`. |
| #137 | merged | Explicit Walker/osculating engineering inputs: removed hidden orbital defaults, explicit argument of perigee/anomaly type, singularity guards and blank-input protection. |
| #138 | merged | Hardened digital-twin perturbation contracts: typed canonical parameter registry, domain-level unit checks and stricter target-scope invariants without changing numerical authority or sampling semantics. |
| #140 | merged | Perturbation Designer now requires explicit scope selection for every enabled rule; no implicit whole-constellation scope remains and empty scope fails closed in the packaged operator UI. |

## Active change

| PR | Status | Engineering increment |
|---|---|---|
| #141 | CI pending | First NORAD-family intake slice: strict TLE and OMM JSON validation/normalization with source SHA-256 provenance. TLE/OMM remain explicitly typed as SGP4/NORAD mean elements and cannot be promoted to a runnable scenario until an authoritative Orekit TLE/SGP4 conversion boundary exists. |

## Current authority boundaries

1. Screening is not design/validation authority.
2. High-fidelity osculating-to-mean conversion is Orekit/DSST-only and fails closed if authority/fingerprints mismatch.
3. Perturbations act on the canonical mean-element representation and never silently reinterpret osculating inputs.
4. NORAD TLE/OMM elements are SGP4 mean elements; they are not osculating Keplerian elements and are not canonical project MeanOrbit values. Runnable promotion is blocked until reviewed Orekit TLE/SGP4 authority exists.
5. Maneuver resource accounting is a preflight/ledger coupled to the same maneuver schedule; it does not replace Orekit impulse physics.
6. A runnable continuation scenario may be created only from complete persisted propagation evidence reaching the exact scenario horizon.
7. Historical runs without persisted `propagation_result.json` are intentionally non-promotable without rerun.

## Current main evidence checkpoint

- PR #140 exact head: `751705fa4b73c8c92bc73ff1b8233c041cfc58ae`.
- Exact-head required workflows all terminal success:
  - `ci` run `33389159950`;
  - `preview-package-compat` run `33389159942`;
  - `preview-0.2-package` run `33389159986`.
- PR #140 merge commit: `1102ea44efa0a4dbb73472d16fdfc151188534f9`.
- PR #140 history checkpoint on main: `9f1d24b86bf6f866a92ea536d2a4c884b4ecd133`.

## Next incomplete work

Priority order after PR #141 acceptance:

1. Add authoritative Orekit TLE/SGP4 propagation/conversion and only then permit NORAD input to produce immutable derived scenarios.
2. Add GNSS almanac-family adapters (YUMA/SEM and GLONASS almanac first) with format-specific authority semantics.
3. Extend propulsion/correction-system catalog semantics and resource-history/operator tooling without creating detached mass models.
4. Evaluate structural lineage hash validation against all existing scenario/test fixtures before tightening the schema; do not break historical derived scenarios merely to enforce formatting.
5. Run package-level Windows acceptance before calling the accumulated 0.2.4 line a distributable release.

## Maintenance rule

Every subsequent engineering PR in the 0.2.4 line must update this file in the same PR with: PR number, functional delta, authority boundary where relevant, and exact evidence checkpoint after merge when known.
