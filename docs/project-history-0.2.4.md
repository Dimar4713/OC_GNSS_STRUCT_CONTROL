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
| #144 | merged | TLE authority extended to an explicit target epoch/time scale. Orekit SGP4/SDP4 propagates in TEME from the TLE source epoch to the parent scenario epoch, transforms the target-epoch osculating PV to the selected inertial frame, then delegates to the existing force-model-consistent DSST mean authority. The exact-epoch usability restriction is removed without mixing constellation epochs. OMM remains blocked. |
| #145 | merged | Strict preview-only GNSS almanac intake for GPS YUMA, GPS SEM and labelled GLONASS interchange text. YUMA radian semantics and SEM semicircle/inclination-offset semantics are preserved explicitly; source SHA-256/provenance is retained; duplicate/malformed records fail closed; no almanac record is silently promoted into canonical MeanOrbit or runnable scenario. |
| #146 | merged | Explicit propulsion/correction catalog contracts and packaged validation UI. Catalog entries verify declared model/type/thrust/Isp/propellant/mode against each spacecraft operational state, but never auto-fill or overwrite mass, fuel, thrust or Isp. Numerical resource authority remains the scenario operational state and spacecraft parameters. |
| #147 | merged | Reviewed GPS almanac authority: raw YUMA/SEM is reparsed by Orekit 13.1.7, selected by PRN, propagated with Orekit's GPS GNSS analytical propagator to the explicit target epoch, transformed to the selected inertial frame, and delegated to the existing force-model-consistent DSST mean authority. GLONASS remains preview-only and cannot reuse this path. |
| #148 | merged | Operator-side GPS YUMA/SEM authority preview and immutable derived-scenario creation. The selected parent satellite is replaced only by the verified #147 Orekit GNSS→DSST mean result; source filename/SHA-256/format/PRN/authority are persisted in typed lineage; source and existing target YAML are never overwritten. GLONASS remains fail-closed. |
| #149 | merged | Dedicated GLONASS almanac authority using explicit authority-ready labelled semantics, Orekit `GLONASSAlmanac` and `GLONASSAnalyticalPropagator`, followed by the existing DSST osculating-to-mean authority. Legacy `draconian_period_s` is never reinterpreted as `deltaT`; incomplete legacy records remain preview-only. |

## Active change

No active merged-target PR at this checkpoint. Next slice is operator-side immutable GLONASS derived-scenario creation, followed by structural lineage hash validation review.

## Current authority boundaries

1. Screening is not design/validation authority.
2. High-fidelity osculating-to-mean conversion is Orekit/DSST-only and fails closed if authority/fingerprints mismatch.
3. Perturbations act on the canonical mean-element representation and never silently reinterpret osculating inputs.
4. NORAD TLE elements may reach canonical MeanOrbit only through `TLE -> Orekit SGP4/SDP4 TEME@explicit target epoch -> osculating PV -> selected inertial frame -> Orekit DSST mean`; raw TLE values are never relabelled as canonical elements.
5. The TLE source epoch and target scenario epoch remain separately recorded. The resulting canonical state is defined only at the explicit target scenario epoch/time scale.
6. OMM remains SGP4/NORAD mean-element intake only and is non-promotable until its own reviewed Orekit conversion boundary exists.
7. GPS YUMA/SEM may reach canonical MeanOrbit only through `raw YUMA/SEM -> Orekit parser -> Orekit GPS GNSS analytical propagator@explicit target epoch -> osculating PV -> selected inertial frame -> Orekit DSST mean`. Python-side normalized almanac values are not a propagation authority and are never copied directly into MeanOrbit.
8. GPS almanac derived scenarios may be created only from a verified #147 sidecar attestation. Source scenario overwrite and target overwrite are forbidden; lineage preserves source format, filename, SHA-256, PRN and authority.
9. GLONASS must not reuse GPS GNSS semantics. A GLONASS record may reach canonical MeanOrbit only through explicit authority-ready almanac semantics -> Orekit `GLONASSAlmanac` -> Orekit `GLONASSAnalyticalPropagator` at the explicit target epoch -> osculating PV in the selected inertial frame -> Orekit DSST mean. The legacy `draconian_period_s` preview field is not silently reinterpreted as Orekit/ICD `deltaT`.
10. Legacy GLONASS labelled-text records that omit calendar date, `deltaT`, `deltaTDot` or time-correction fields remain preview-only and fail closed for authority conversion.
11. Maneuver resource accounting is a preflight/ledger coupled to the same maneuver schedule; it does not replace Orekit impulse physics.
12. Propulsion/correction catalog data is validation/reference metadata only. It must not auto-populate or override current mass, propellant mass, thrust or Isp; those remain explicit scenario/operational-state numerical authority.
13. A runnable continuation scenario may be created only from complete persisted propagation evidence reaching the exact scenario horizon.
14. Historical runs without persisted `propagation_result.json` are intentionally non-promotable without rerun.

## Current main evidence checkpoint

- PR #149 exact head: `1d4ac2e5ee7c8fc2f96f7158d65b4adcdd09f7b5`.
- Exact-head required workflows all terminal success:
  - `ci` run `33415381271`;
  - `preview-package-compat` run `33415381057`;
  - `preview-0.2-package` run `33415381037`.
- PR #149 merge commit: `833e3480b5df69716484cdff5160c2b35229a307`.
- Prior PR #148 merge commit: `4329b6eff757c098dc1b5af883db03d68464679f`.

## Next incomplete work

1. Wire operator-side immutable GLONASS derived-scenario creation only through verified #149 sidecar attestation.
2. Evaluate structural lineage hash validation against all existing scenario/test fixtures before tightening the schema; do not break historical derived scenarios merely to enforce formatting.
3. Run package-level Windows acceptance before calling the accumulated 0.2.4 line a distributable release.

## Maintenance rule

Every subsequent engineering PR in the 0.2.4 line must update this file in the same PR with: PR number, functional delta, authority boundary where relevant, and exact evidence checkpoint after merge when known.
