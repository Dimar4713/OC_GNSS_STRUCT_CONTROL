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
| #141 | merged | First NORAD-family intake slice: strict TLE and OMM JSON validation/normalization with source SHA-256 provenance. TLE/OMM remain explicitly typed as SGP4/NORAD mean elements and runnable promotion remains blocked until authoritative Orekit TLE/SGP4 conversion exists. |
| #142 | merged | Authoritative TLE conversion boundary: Orekit 13.1.7 validates raw TLE, selects SGP4/SDP4 in explicit TEME, evaluates osculating PV at the TLE epoch, transforms to selected Earth-centered inertial frame, and delegates to the existing force-model-consistent Orekit DSST osculating-to-mean authority. OMM remains fail-closed. |
| #143 | merged | Consolidated operator TLE authority flow and immutable derived-scenario creation. Raw TLE is promoted only after verified Orekit SGP4/TEME→DSST authority, parent YAML is never overwritten, NORAD source SHA/record/authority are persisted in lineage, and epoch mismatch fails closed. OMM remains blocked. |

## Active change

| PR | Status | Engineering increment |
|---|---|---|
| #144 | CI pending | Extend the authoritative TLE boundary with explicit target epoch/time scale. Orekit SGP4/SDP4 propagates in TEME from the TLE epoch to the parent scenario epoch, transforms the resulting osculating PV to the selected inertial frame, then delegates to the existing DSST mean authority. The prior exact-epoch restriction is removed without mixing constellation epochs. OMM remains blocked. |

## Current authority boundaries

1. Screening is not design/validation authority.
2. High-fidelity osculating-to-mean conversion is Orekit/DSST-only and fails closed if authority/fingerprints mismatch.
3. Perturbations act on the canonical mean-element representation and never silently reinterpret osculating inputs.
4. NORAD TLE elements may reach canonical MeanOrbit only through `TLE -> Orekit SGP4/SDP4 TEME@explicit target epoch -> osculating PV -> selected inertial frame -> Orekit DSST mean`; raw TLE values are never relabelled as canonical elements.
5. The TLE source epoch and target scenario epoch remain separately recorded. The resulting canonical state is defined only at the explicit target scenario epoch/time scale.
6. OMM remains SGP4/NORAD mean-element intake only and is non-promotable until its own reviewed Orekit conversion boundary exists.
7. Maneuver resource accounting is a preflight/ledger coupled to the same maneuver schedule; it does not replace Orekit impulse physics.
8. A runnable continuation scenario may be created only from complete persisted propagation evidence reaching the exact scenario horizon.
9. Historical runs without persisted `propagation_result.json` are intentionally non-promotable without rerun.

## Current main evidence checkpoint

- PR #143 exact head: `1fea94e1b906a79b666d5cc1c36dedc5c0b10ee0`.
- Exact-head required workflows all terminal success:
  - `ci` run `33400824359`;
  - `preview-package-compat` run `33400824360`;
  - `preview-0.2-package` run `33400824350`.
- PR #143 merge commit: `41e1027adc3f2513beb345809bf633fe7790067d`.
- PR #144 evidence is pending on its exact head.

## Next incomplete work

Priority order after PR #144 acceptance:

1. Add GNSS almanac-family adapters (YUMA/SEM and GLONASS almanac first) with format-specific authority semantics.
2. Extend propulsion/correction-system catalog semantics and resource-history/operator tooling without creating detached mass models.
3. Evaluate structural lineage hash validation against all existing scenario/test fixtures before tightening the schema; do not break historical derived scenarios merely to enforce formatting.
4. Run package-level Windows acceptance before calling the accumulated 0.2.4 line a distributable release.

## Maintenance rule

Every subsequent engineering PR in the 0.2.4 line must update this file in the same PR with: PR number, functional delta, authority boundary where relevant, and exact evidence checkpoint after merge when known.
