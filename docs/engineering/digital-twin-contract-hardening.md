# Digital-twin contract hardening

This note tracks the 0.2.4 hardening slice that follows the explicit Walker/osculating-input cleanup.

Implemented in PR #138:

- perturbation parameters use a canonical typed registry (`a_m`, `e`, `i_rad`, `raan_rad`, `argp_rad`, `mean_anomaly_rad`) rather than arbitrary strings;
- canonical units are validated in the domain contract for requested and applied perturbations;
- constellation-scope rules cannot carry target IDs;
- duplicate target IDs are rejected;
- serialized JSON/YAML values remain compatible with the existing string representation;
- regression tests cover unknown parameters, wrong units, target-scope invariants and applied-sample unit validation.

No propagation authority, force model, integrator, maneuver physics, perturbation sampling algorithm, precedence rule, or mean/osculating conversion authority is changed by this slice.

Acceptance evidence is the required `ci`, `preview-package-compat` and `preview-0.2-package` gates on the exact PR head. Merge evidence is added to `docs/project-history-0.2.4.md` after acceptance.
