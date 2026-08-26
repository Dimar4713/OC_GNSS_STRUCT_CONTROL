# P1 duration presets — invariants and acceptance plan

Parent: #23.

## Operator presets

The Preview completion slice will offer explicit propagation horizons:

- 1 day = 86,400 s
- 8 days = 691,200 s
- 30 days = 2,592,000 s
- 90 days = 7,776,000 s
- 1 Julian year = 31,557,600 s
- 5 Julian years = 157,788,000 s
- custom duration in seconds/days, validated as positive and finite

## Hard invariants

Selecting a duration preset may change only `ScenarioConfig.duration_s` for the submitted run copy.

It must not silently change:

- `force_model.mode` / fidelity authority;
- force-model fields or fingerprint;
- integrator configuration;
- `output_step_s`;
- epoch, frame, or time scale;
- constellation geometry;
- maneuver definitions.

The source YAML remains unchanged. The selected run must preserve the effective normalized scenario in the run artifacts.

## Operational safety

A long horizon is not permission to lower fidelity. DESIGN and VALIDATION remain fail-closed if their Orekit authority is unavailable.

The UI must make duration and unchanged output step visible before execution. Large point counts should be reported explicitly; no automatic coarse resampling is allowed in this P1 slice.

## Acceptance

Tests must prove for every preset that:

1. only `duration_s` differs from the source scenario;
2. force-model fingerprint is unchanged;
3. fidelity mode is unchanged;
4. integrator is unchanged;
5. `output_step_s` is unchanged;
6. custom invalid/non-positive/non-finite duration is rejected;
7. the API run artifacts record the selected duration;
8. Windows Preview smoke and full CI remain GREEN.
