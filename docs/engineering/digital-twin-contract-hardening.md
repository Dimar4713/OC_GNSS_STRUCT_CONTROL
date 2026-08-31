# Digital-twin contract hardening

This note tracks the 0.2.4 hardening slice that follows the explicit Walker/osculating-input cleanup.

## Implemented in this slice

- Perturbation parameters are selected from a canonical `PerturbationParameter` registry rather than arbitrary strings.
- Supported engineer-facing parameters are: semi-major axis, eccentricity, inclination, RAAN, argument of perigee, mean anomaly, and epoch offset.
- Each parameter has one canonical unit contract (`m`, `1`, `rad`, or `s`); a mismatched unit is rejected before execution.
- Constellation-scope rules must not carry target IDs; plane/group/satellite rules require explicit targets.
- Applied perturbation evidence uses the same parameter/unit registry as the requested rule.
- Scenario lineage requires a real lowercase SHA-256 parent config hash.
- Regression tests cover unsupported parameter names, wrong units, ambiguous scope targeting, applied-evidence consistency, and lineage hash validation.

## Authority boundary

This hardening slice does **not** yet apply sampled deltas to orbital state. It makes the input/evidence contract fail-closed before the deterministic sampling and derived-scenario mutation layer is connected.

No propagation authority, force model, integrator, maneuver physics, or mean/osculating conversion authority is changed by this slice.

## Next

1. deterministic seeded sampler;
2. target resolution with precedence `satellite > group > plane > constellation`;
3. classical-parameter-to-canonical-mean conversion with singularity guards;
4. immutable derived-scenario save with all actual samples recorded in `applied_perturbations`;
5. packaged operator Perturbation Designer UI.
