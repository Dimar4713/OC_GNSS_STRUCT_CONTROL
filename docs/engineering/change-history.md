# Engineering change history

This log records repository-level engineering changes that materially affect the operator workflow, numerical authority boundaries, scenario contracts, packaging, or release readiness.

## 2026-08-31

### PR #137 — explicit Walker and osculating engineering inputs

Merged exact head `c245e89c6d9f15c2c5025c5f9f1d6149b8a95a57` after `ci`, `preview-package-compat`, and `preview-0.2-package` completed successfully.

Merge commit: `796c9fc820834347b782e71ad352ba86f36efd9b`.

Material changes:

- removed hidden numeric defaults from Walker and osculating packaged inputs;
- made Walker RAAN0, argument of perigee, and mean anomaly explicit;
- corrected Walker equinoctial `ex/ey/lambda` mapping for explicit argument of perigee;
- rejected the 180-degree equinoctial inclination singularity;
- made osculating anomaly type explicitly selected by the engineer;
- guarded blank browser numeric fields from silently becoming zero;
- preserved Orekit/DSST numerical authority and force-model semantics.

### 0.2.4 perturbation contract hardening — in development

Branch: `feat/perturbation-designer-core`, based on current `main` `2a608c81c22bd78fdc30c7e17fc27034e3ef3674`.

Material changes in the current slice:

- canonical perturbation-parameter registry;
- canonical unit contract per parameter;
- fail-closed rejection of unsupported parameter names and units;
- unambiguous scope/target contract;
- applied-perturbation evidence tied to the same registry;
- SHA-256 validation for parent scenario lineage;
- regression tests for the new contract.

Numerical authority boundary: this slice does not yet mutate orbital state or alter propagation, force model, integrator, maneuver physics, or mean/osculating conversion authority.
