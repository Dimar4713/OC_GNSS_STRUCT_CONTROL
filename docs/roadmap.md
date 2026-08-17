# Roadmap

## R0 — reproducible screening MVP
Issues #2–#5. Establish schemas, deterministic run identity, J2 screening, ROE/harmonic drift analysis, optimisation/control primitives, Monte Carlo, artifacts and CI. Exit criterion: green PR with end-to-end artifact evidence.

## R1 — authoritative Orekit design backend
Issue #6. Implement DSST force stack and mean↔osculating conversion with explicit frame/time-scale/data versions. Add force-model fingerprint evidence.

## R2 — numerical validation and linearisation
Issue #6. Full numerical propagation, manoeuvre models, variational equations or finite-difference `A/B`, top-K design replay and controller post-validation.

## R3 — constellation design mission
Bind `[Delta a, Delta ex, Delta ey, Delta ix, Delta iy, Delta lambda0]` per additional spacecraft to LHS -> SLSQP/trust-constr -> NSGA-II -> validation. Persist Pareto tables and explicit recommendation policy.

## R4 — robust operations
Full uncertainty model, parallel/HPC runs, long-horizon fuel/lifetime forecast, navigation geometry provider, repeat-ground-track closure validation and operational report templates.

## AIMETON governance
Each release gate closes only with reproducible artifacts and CI evidence. Unknown physics/model choices become tracked decisions, not implicit defaults.
