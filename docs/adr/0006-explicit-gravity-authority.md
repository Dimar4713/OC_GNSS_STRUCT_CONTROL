# ADR-0006 — Explicit gravity-model authority

Status: Accepted

Date: 2026-08-17

## Context

The reviewed `orekit-data` directory contains multiple gravity-coefficient formats/models. During high-fidelity HTTP E2E, the standalone Java sidecar selected a gravity provider whose gravitational parameter differed from the configured scenario value by about `8.176e-8`, while an in-process integration-test JVM selected a provider with `mu = 3.986004415e14`, compatible at about `7.5e-10` relative difference.

The same code and the same auxiliary-data revision therefore produced a different provider identity depending on lazy reader/load history. Increasing the accepted `mu` tolerance would hide the authority ambiguity rather than solve it.

## Decision

1. High-fidelity force models (`design`, `validation`) must declare `gravity_model` explicitly.
2. The first supported authority is `EIGEN-6S`.
3. The Orekit runtime clears automatically configured potential-coefficient readers and installs only an `ICGEMFormatReader` matching `^eigen-6s-truncated$`.
4. `gravity_model` is part of the normalized pydantic force-model payload and therefore part of the SHA-256 force-model fingerprint.
5. The Java service rejects a request whose declared gravity authority differs from the runtime authority.
6. Result metadata repeats `gravity_model`, gravity-provider `mu`, gravity-provider reference radius `Ae`, and the separately configured Earth ellipsoid radius/flattening.
7. The strict configured-vs-provider `mu` compatibility check remains; its tolerance is not widened to compensate for model-selection ambiguity.
8. Screening remains independent of this high-fidelity gravity authority and may omit `gravity_model`.

## Consequences

- Clean sidecar startup, Java integration tests, Python HTTP calls and run manifests identify the same gravity authority.
- Adding another gravity model requires a deliberate schema/adapter/runtime change and validation evidence; dropping a file into `orekit-data` cannot silently change physics.
- Historical run manifests remain interpretable because the force-model fingerprint changes when gravity authority changes.
- The authority decision is orthogonal to the `orekit-data` revision/content SHA: model identity and auxiliary-data identity are both recorded.

## Rejected alternatives

### Widen the `mu` tolerance

Rejected. It would allow different coefficient families to pass under the same scenario fingerprint.

### Trust Orekit automatic reader selection

Rejected for production authority. Lazy reader selection is convenient for exploratory use but does not provide the deterministic model identity required by this platform.

### Hard-code provider constants while leaving model selection automatic

Rejected. Matching constants does not prove which coefficient field generated the forces.
