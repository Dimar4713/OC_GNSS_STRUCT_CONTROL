# Engineering Preview 0.2 — Optimal Operations Study Profile

## Status
The #101 foundation contract is accepted. The #103 execution slice adds authoritative P2 baseline comparison plus screening-only optimized candidate search. Hybrid candidate validation, robustness binding and final recommendation remain later stages.

## Core rule
The Preview does not supply operational, search or robustness numbers. Every horizon, maximum correction count, controlled deputy, authority grid/window, MPC execution limit/weight, search bound/population/generation count, seed, objective definition, hard-constraint definition and robustness policy is explicitly present in the profile.

The only model default is the metadata-only schema identifier `preview-optimal-operations-study-profile-v1`.

## Compatibility identity
Preflight derives the accepted `OperationalStudyIdentity` from the selected validated ScenarioConfig plus the explicit profile and verifies operator-declared expectations for:
- force-model fingerprint;
- frame and time scale;
- integrator identity;
- constraints identity;
- execution-policy identity;
- exact authority time grid and maneuver windows.

The profile also names `controlled_deputy_id` explicitly. Preflight requires that satellite to have role `additional` and resolves its declared `reference_id` before any execution. This pair identity is retained in preflight evidence and downstream provenance.

`max_corrections` is explicit because the accepted P2 campaign runner requires it. Preview 0.2 must not manufacture a campaign safety/termination limit.

Integrator, constraints and execution-policy identities are deterministic SHA-256 digests of canonical JSON payloads. Scenario force-model identity reuses the accepted `ForceModelConfig.fingerprint()` contract.

## Authoritative P2 baselines
The execution adapter runs exactly three P2 strategy identities under the same preflight:
- NO CONTROL;
- RETURN TO CENTER;
- BOUNDARY TO BOUNDARY.

RTC/B2B continue to use the accepted `run_closed_loop_campaign()` numerical maneuver-authority path and accepted resource ledger. NO CONTROL preserves the existing zero-authority P2 behavior: the control campaign itself performs no propagation or maneuver-authority attempt.

For physically comparable strategy evidence, every baseline is then replayed from the same initial state over the full declared study horizon with the exact maneuvers recorded in its accepted resource ledger. NO CONTROL therefore becomes a full-horizon numerical coast with zero maneuvers; controlled strategies become full-horizon numerical replays of their exact authorized maneuver histories.

The replay must report an `orekit-numerical*` backend and the exact study force-model fingerprint. A controlled campaign that did not cover the declared campaign horizon is rejected before baseline assembly.

## Hard-margin semantics
Hard constraints remain signed evidence and are never folded into optimizer weights.

Current baseline reducers support:
- `phase_corridor_margin [rad]`: minimum direct operator mean-phase corridor margin on the full-horizon numerical replay output grid;
- `minimum_fleet_distance_margin [m]`: minimum all-pairs Cartesian separation margin on the same replay output grid;
- `propellant_reserve_margin [kg]`: accepted P2 terminal resource-ledger margin above configured reserve.

A hard-failing baseline is **not erased**. It remains an authoritative baseline measurement with negative signed margin and is therefore non-credible for later credible-Pareto selection. This is essential for honest NO CONTROL comparison.

The trajectory reducer performs no propagation, interpolation, control decision or maneuver sizing. It only reduces already-authoritative `PropagationResult` samples. Output-grid semantics are retained explicitly; no hidden interpolation is introduced.

## Operational objectives
Objective definitions are explicit. Supported evidence is reduced only from accepted P2 campaign/resource metrics. Unavailable annualization or lifetime remains unavailable and causes a requested objective to fail closed rather than fabricating zero/infinity.

NO CONTROL is a special exact policy case for correction, delta-V and propellant rates: with a declared full-horizon numerical zero-maneuver replay, these control-consumption rates are exactly zero. No lifetime value is invented from that zero consumption.

## Search
Preview requires every field of the accepted `OperationalPolicySearchConfig` explicitly, including fields for which the backend class has general-purpose defaults (`local_seeds`, `local_method`, `nsga_population`, `nsga_generations`). This prevents backend defaults from silently becoming operator policy.

The #103 adapter calls only the accepted `run_operational_policy_screening_search()` with the exact preflighted config. Its evaluator is supplied by the accepted screening layer rather than reimplemented in Preview. Every returned candidate must remain `screening_only=True`.

Search bounds are dimensionless `trigger_fraction` and `target_fraction`. Physical corridor/safety constants are not optimizer variables. `pareto_candidate_ids` at this stage mean only the screening nondominated set; they are not the credible operational Pareto set and cannot authorize a recommendation.

## Robustness
Robustness is an explicit policy:
- disabled: recommendation cannot require robustness and campaign/model/hash evidence must be explicitly null;
- enabled: campaign id, uncertainty-model id and sampling-model SHA-256 are mandatory.

Disabled robustness means unavailable robustness evidence. It never means zero probability or zero risk. The #103 slice does not execute or fabricate robustness evidence.

## Artifacts
The #103 foundation run persists deterministic machine-readable evidence:
- `optimal_operations_preflight.json`;
- `operational_baselines.json`;
- `screening_candidates.json`;
- `foundation_manifest.json`.

The run directory is content-addressed from the complete foundation evidence. The manifest explicitly carries `recommendation_strategy_id: null` and `screening_only: true`.

## Authority boundary
Screening candidates cannot become operationally credible in #103. Hybrid high-fidelity validation is the next authority transition. Final objectives for any optimized candidate must later come from authoritative operational outcomes, never from screening scores.
