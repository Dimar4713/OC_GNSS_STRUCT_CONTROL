# Optimisation

## Design vector
For every additional spacecraft the external design vector is

`[Delta a, Delta ex, Delta ey, Delta ix, Delta iy, Delta lambda_0]`.

No operational values are hardcoded; bounds and constraints are scenario inputs.

## Objective
The weighted scalar design objective combines squared secular phase drift, periodic phase amplitude, plane-vector drift, proximity penalty, repeat-ground-track error and estimated lifetime delta-V.

## Search sequence
1. Latin Hypercube screening (`scipy.stats.qmc`).
2. Local refinement using `SLSQP` or `trust-constr`.
3. NSGA-II (`pymoo`) for the stability–delta-V–minimum-distance Pareto surface.
4. Top-K replay through the validation backend.
5. Explicit policy selects the recommended nondominated solution.

The MVP implements generic LHS, local optimisation and NSGA-II primitives. The next application-layer step is to bind them to full constellation metrics and Orekit top-K replay.
