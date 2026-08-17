# Design pipeline authority flow

The production design search is intentionally split into a cheap search authority and a final validation authority.

## Design variables

For every additional spacecraft the pipeline consumes exactly six variables, in this order:

`[Δa, Δex, Δey, Δix, Δiy, Δλ0]`.

The vector is always interpreted relative to the selected reference spacecraft. The same vector semantics are applied to the screening scenario and the numerical-validation scenario; force-model-specific mean-element definitions remain local to each scenario.

## Search stages

1. Generate deterministic Latin-hypercube candidates and an optional bounded Cartesian grid.
2. Evaluate candidates with the screening propagator.
3. Remove candidates that violate any hard constraint margin.
4. Select deterministic local-refinement seeds with the explicit recommendation policy.
5. Refine with SciPy SLSQP or trust-constr while passing hard constraints as true nonlinear inequalities, not weighted penalties.
6. Run constrained NSGA-II. Constraint margins are converted to pymoo's `G <= 0` convention.
7. Deduplicate equal final design vectors, compute the feasible nondominated set and rank it with a versioned recommendation policy.
8. Replay top-K Pareto candidates through `orekit-numerical-validation`.
9. Emit a recommendation only when the recommended candidate has numerical Orekit replay evidence.

## Objectives in the current application adapter

The current scenario adapter minimizes three explicit quantities:

- relative-phase stability envelope: fitted secular phase drift over the scenario horizon plus harmonic amplitude;
- design ΔV proxy derived from small relative semi-major-axis, eccentricity-vector and inclination-vector offsets;
- negative minimum pair distance, so greater separation is preferred by minimization.

The ΔV term is deliberately named a **design ΔV proxy**. It is not presented as a full lifetime station-keeping budget. Lifetime robustness and operational uncertainty remain part of the later Monte Carlo/robustness campaign.

## Hard constraints

For each additional spacecraft the pipeline checks:

- lower and upper Δa bounds;
- relative eccentricity-vector magnitude;
- relative inclination-vector magnitude;
- initial phase corridor.

A fleet-level minimum pair-distance margin is also mandatory. Infeasible candidates cannot enter the final Pareto set or top-K replay.

## Recommendation policy

`weighted-normalized-v1` normalizes each objective over the current candidate set and applies configured non-negative weights. The policy version and weights are persisted. Ties use stable candidate identifiers; the system never invents an implicit preferred Pareto compromise.

## Authority boundary

Screening, local optimization and NSGA-II are search/ranking mechanisms only. They cannot authorize a final design claim.

A final recommendation requires:

- backend identity `orekit-numerical-validation`;
- matching force-model fingerprint through the Orekit adapter;
- explicit gravity authority `EIGEN-6S`;
- Orekit version and pinned orekit-data revision/SHA provenance;
- successful replay of the exact recommended design vector.

No instantaneous osculating semi-major axis is used as a secular-drift criterion. Secular phase metrics continue to use force-model-consistent mean-element histories and harmonic regression.

## Evidence artifacts

A design run writes:

- `pipeline_manifest.json`;
- `candidates.csv` / `candidates.parquet`;
- `pareto.csv` / `pareto.parquet`;
- `validation.json`;
- `recommendation.json`;
- `report.md` / `report.html`.

CI verifies candidate lineage, Pareto membership, recommendation-to-validation binding and numerical Orekit provenance before the design pipeline is accepted.
