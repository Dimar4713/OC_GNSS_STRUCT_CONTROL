# Architecture

## Shape
The platform uses clean/hexagonal architecture. `domain` owns schemas and Protocol ports. Physics/application code depends on those ports. `adapters/*` provide concrete propagation backends. No domain module imports Orekit, JPype, FastAPI or CLI code.

## Runtime flow
`YAML -> ScenarioConfig -> PropagationRequest -> Propagator -> PropagationResult -> ROE/drift/stability analysis -> optimisation/control/uncertainty -> artifact writer`.

## Fidelity boundary
`screening` is implemented in-process by `SyntheticMeanPropagator`. `design` and `validation` require an Orekit backend. The current production boundary is `OrekitSidecarPropagator`, POSTing the validated request to `/v1/propagate` and requiring an Orekit backend identity plus an exact force-model fingerprint match.

## Determinism
Configuration is normalized through pydantic and SHA-256 hashed. The run ID is UUIDv5 over scenario ID, config hash, seed and code version. Monte Carlo samples are generated before parallel dispatch, so worker scheduling cannot change the sample set.

## State representations
- storage/design: nonsingular equinoctial mean representation `(a, ex, ey, ix, iy, lambda)`;
- relative control: D'Amico ROE;
- numerical propagation exchange: Cartesian position/velocity states.

## Extension points
`Propagator`, `LinearizationProvider`, `NavigationGeometryProvider` and `PlanSafetyValidator` are ports. Future adapters may include direct JPype Orekit, Java sidecar, batch/HPC execution, navigation geometry and external mission databases without changing domain logic.
