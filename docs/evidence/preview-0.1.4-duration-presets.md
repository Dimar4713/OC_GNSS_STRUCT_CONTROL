# Engineering Preview 0.1.4 — duration preset evidence

Parent: #23. Implementation issue: #36. PR: #37.

## Operator capability

Engineering Preview 0.1.4 adds explicit propagation horizons:

- 1 d = 86,400 s
- 8 d = 691,200 s
- 30 d = 2,592,000 s
- 90 d = 7,776,000 s
- 1 Julian year = 31,557,600 s
- 5 Julian years = 157,788,000 s
- custom positive finite duration

The scenario-declared duration remains the default.

## Hard invariant

A duration selection changes only the effective run `duration_s`.

The implementation regression-tests that the following remain unchanged:

- `force_model.mode` and full force model;
- force-model fingerprint;
- integrator;
- `output_step_s`;
- epoch, frame and time scale;
- constellation geometry;
- maneuver definitions.

The effective scenario is reconstructed through full `ScenarioConfig.model_validate`; unchecked Pydantic copying is intentionally not used. Therefore a shortened duration that would leave a configured maneuver outside the run horizon is rejected.

The source YAML is not overwritten. The effective normalized scenario is persisted in the normal run evidence as `scenario.normalized.json`.

## Output grid contract

The current propagation contract emits regular output-step samples and appends the exact final duration when needed. Predicted output sample count is therefore:

`ceil(duration_s / output_step_s) + 1`

Tests cover both divisible and non-divisible horizons.

No automatic output-step coarsening or resampling is allowed in this P1 slice.

## Authority safety

Duration selection is not a fidelity selector. DESIGN and VALIDATION remain fail-closed and continue to require their configured Orekit authority. A long horizon never permits silent fallback to SCREENING.

## Execution architecture

`run_scenario_with_duration()` resolves and validates the effective duration, then executes the existing authoritative `run_scenario()` pipeline. For an override it serializes a temporary internal effective scenario, calls the existing pipeline, and deletes the temporary file. This avoids a second propagation/reporting implementation.

## Required merge evidence

- Ruff GREEN;
- mypy GREEN;
- full pytest GREEN;
- Preview HTTP E2E for default and custom duration;
- invalid custom-duration rejection;
- source-YAML immutability and normalized effective-scenario evidence;
- Windows Preview smoke including duration tests;
- Engineering Preview 0.1.4 bundle/manifest verification;
- complete Orekit DSST / numerical / MPC / robustness / top-K regression chain GREEN.
