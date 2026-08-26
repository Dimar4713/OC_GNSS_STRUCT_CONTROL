# Engineering Preview 0.1.3 — relative operations UI evidence

Parent: #23. Implementation issue: #32.

## Authority chain

The Preview does not recompute orbital relative diagnostics.

1. `run_scenario()` propagates the configured scenario using the selected fidelity authority.
2. `run_scenario()` writes `summary.json:relative_operations` and timeseries evidence.
3. `preview_operations_payload()` reads that persisted summary and only converts presentation units (`m -> km`) / selects fields for the UI.
4. Preview displays the projection and exposes only explicitly allowed generated report artifacts.

## Operator quantities

- `Delta u = u_mean(additional) - u_mean(reference)`, where `u_mean = lambda - Omega = M + omega` for the authoritative mean element set.
- D'Amico `delta_lambda` remains a separate coordinate and is not relabelled.
- `Delta s ~= a_ref * Delta u` is a near-circular mean along-track arc proxy, not Cartesian spacecraft separation.
- phase-corridor half-width is exactly the scenario `constraints.phase_corridor_rad`.
- time-to-boundary is a linear secular forecast, not a closed-loop control command.

## Fail-safe display rules

- zero secular phase rate -> no invented finite time-to-boundary;
- already outside configured corridor -> time-to-boundary = 0;
- no additional/reference pair -> operator UI reports that relative diagnostics are unavailable;
- arbitrary result files are not exposed through the Preview artifact route.

## Required gates

- Ruff / mypy / pytest;
- Preview HTTP E2E including persisted operations projection and artifact allow-list;
- Windows PowerShell launcher parse and HTTP loopback tests;
- Windows bundle build / manifest version `Engineering Preview Python 0.1.3`;
- full Orekit DSST / numerical / MPC / robustness / design-search regression suite.
