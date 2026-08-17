# Architecture

## Shape

The platform uses clean/hexagonal architecture. `domain` owns immutable schemas and Protocol ports. Physics/application code depends on those ports. `adapters/*` provide concrete propagation backends. No domain module imports Orekit, HTTP, FastAPI or CLI code.

## Runtime flow

`YAML -> ScenarioConfig -> PropagationRequest -> Propagator -> PropagationResult -> mean-element ROE/drift/stability analysis -> optimisation/control/uncertainty -> artifact writer`.

## Fidelity authorities

### Screening

`SyntheticMeanPropagator` is an in-process two-body + first-order J2 screening backend. It is intentionally incapable of satisfying a design or validation request.

### Design

`OrekitSidecarPropagator` calls the Java service at `POST /v1/propagate`. In `design` mode the Java authority uses Orekit 13.1.7 DSST and returns DSST-consistent mean equinoctial states plus corresponding osculating Cartesian states. Zonal/tesseral gravity, Moon, Sun and SRP are represented when enabled.

### Validation

In `validation` mode the Java authority numerically propagates Cartesian osculating states and derives output mean elements through the same DSST mean-element family used to define the initial condition. The Python adapter rejects a response unless the backend identity is Orekit, the exact force-model fingerprint matches, a backend version is present and an `orekit_data_sha256` fingerprint is present.

Relativity and tides are currently rejected in validation because the numerical force alone is insufficient: a compatible mean-element conversion must represent the same force model before secular metrics may be claimed. This is a deliberate fail-closed boundary, not a numerical limitation hidden by fallback.

There is no silent design/validation fallback to screening.

## Orekit service boundary

The Java sidecar lives under `sidecar/orekit-service` and is independently buildable/containerizable. It requires a mounted `OREKIT_DATA_PATH` and refuses to start without usable time/EOP data. CI pins the official data repository to a concrete revision, reports the current official main revision for drift visibility, and the runtime hashes the entire loaded data directory.

The sidecar keeps code identity, Orekit library identity and auxiliary physical-data identity separate. Its result metadata records frame, time scale, gravity degree/order, gravity provider constants and Earth ellipsoid parameters.

## State representations

- storage/design: nonsingular equinoctial mean representation `(a, ex, ey, ix, iy, lambda)`;
- relative control: D'Amico ROE `(delta-a, delta-lambda, delta-ex, delta-ey, delta-ix, delta-iy)`;
- numerical authority: Cartesian osculating position/velocity states;
- manoeuvres: impulsive RTN/QSW vectors.

Mean elements always carry a definition tied to the force-model SHA-256. The loader resolves the scenario marker to the actual fingerprint and rejects foreign definitions.

## Control linearization

`FiniteDifferenceRoeLinearizationProvider` is a validation-only adapter-level service that derives time-varying `A[k]`, `B[k]`, `d[k]` by repeated authoritative propagation. It does not hardcode a constant relative-motion matrix. The inverse D'Amico coordinate mapping is local and preserves mean-element provenance.

## Determinism and provenance

Configuration is normalized through pydantic and SHA-256 hashed. The run ID is UUIDv5 over scenario ID, config hash, seed and code version. Monte Carlo samples are generated before parallel dispatch, so worker scheduling cannot change the sample set.

Every run manifest includes the full force model, integrator tolerances, constraints, epoch, frame, time scale, mean-element definitions, backend identity/version/metadata, configuration hash, code version and random seed.

## Extension points

`Propagator`, navigation geometry and safety-validation ports remain independent of the concrete Orekit transport. A future direct-JPype adapter, remote batch/HPC execution or alternate numerical authority can be introduced without moving domain logic. Any new backend must satisfy the same provenance and no-fallback contracts before it can become an authority.
