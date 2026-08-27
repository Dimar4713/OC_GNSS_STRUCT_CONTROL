# Engineering Preview 0.2 — Optimal Operations Study Profile

## Status
Foundation contract for #100 / #101. This document describes read-only preflight only. No propagation, optimization, maneuver authorization or Monte Carlo execution is introduced by this slice.

## Core rule
The Preview does not supply operational, search or robustness numbers. Every horizon, authority grid/window, MPC execution limit/weight, search bound/population/generation count, seed, objective definition, hard-constraint definition and robustness policy is explicitly present in the profile.

The only model default is the metadata-only schema identifier `preview-optimal-operations-study-profile-v1`.

## Compatibility identity
Preflight derives the accepted `OperationalStudyIdentity` from the selected validated ScenarioConfig plus the explicit profile and verifies operator-declared expectations for:
- force-model fingerprint;
- frame and time scale;
- integrator identity;
- constraints identity;
- execution-policy identity;
- exact authority time grid and maneuver windows.

Integrator, constraints and execution-policy identities are deterministic SHA-256 digests of canonical JSON payloads. Scenario force-model identity reuses the accepted `ForceModelConfig.fingerprint()` contract.

## Search
Preview requires every field of the accepted `OperationalPolicySearchConfig` explicitly, including fields for which the backend class has general-purpose defaults (`local_seeds`, `local_method`, `nsga_population`, `nsga_generations`). This prevents backend defaults from silently becoming operator policy.

Search bounds are dimensionless `trigger_fraction` and `target_fraction`. Physical corridor/safety constants are not optimizer variables.

## Robustness
Robustness is an explicit policy:
- disabled: recommendation cannot require robustness and campaign/model/hash evidence must be explicitly null;
- enabled: campaign id, uncertainty-model id and sampling-model SHA-256 are mandatory.

Disabled robustness means unavailable robustness evidence. It never means zero probability or zero risk.

## Authority
Optimal-operations preflight currently requires a VALIDATION ScenarioConfig with configured Orekit numerical authority. Screening candidates generated later cannot become operationally credible without the accepted high-fidelity validation path.

## Determinism
For the same ScenarioConfig and profile, preflight produces the same `OperationalStudyIdentity`, canonical evidence payload and `preflight_sha256`. The function performs no propagator, optimizer or uncertainty-campaign call.
