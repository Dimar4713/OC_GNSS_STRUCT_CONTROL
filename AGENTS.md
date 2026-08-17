# AIMETON execution contract for OC_GNSS_STRUCT_CONTROL

## Mission rule
Work is performed as an evidence-driven engineering mission, not as isolated code generation. Keep the system objective visible across commits, issues, tests and reports.

## Required execution loop
1. Read the parent mission and active P0 issue.
2. Make the smallest coherent architectural change that advances an acceptance gate.
3. Add or update automated evidence (test, schema validation, artifact or CI gate).
4. Inspect the actual result.
5. Continue to the next safe step; do not stop at a local success while an immediately actionable gate remains.
6. Record unresolved physical/technical uncertainty explicitly rather than hiding it behind defaults.

## Physics safety rules
- Never optimise secular drift using instantaneous osculating `a`.
- Never compare mean elements produced by different force-model definitions without explicit conversion.
- Never label screening output as design/validation evidence.
- Never silently fall back from Orekit to a lower-fidelity backend.
- Never invent operational constellation parameters in code; scenario values belong to configuration.
- Hard safety constraints fail closed.

## Change-management rule
Preserve working behaviour unless a change has a stated acceptance reason and regression evidence. Refactors must not silently alter physical semantics, units, frames, time scales or mean-element definition.

## Evidence before closure
An issue is closed only when code, tests/docs and CI evidence satisfy its acceptance criteria. A PR description must list assumptions, unresolved limitations and the next fidelity gate.
