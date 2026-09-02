# DSST mean-conversion convergence boundary — issue #186

This diagnostic is based on the exact engineer-supplied validation scenario preserved in `scenarios/regression/glo_source_linearization_validation_engineer.yaml`.

Observed authoritative Orekit 13.1.7 evidence on the pinned Orekit-data revision:

- 1 day: converges.
- 100 days: converges.
- 1 year: first failure occurs for `GLO-01` at output point 469203, `time_s=14076060`, epoch `2020-06-11T22:01:00Z`.
- failure originates in `FixedPointConverter.convertToMean` called by `DSSTPropagator.computeMeanState` after 201 iterations.

The follow-up boundary probe is deliberately diagnostic-only. It changes only scenario duration while preserving force model, gravity, integrator, 30 s output step, epoch, satellite definitions, and Orekit authority.

Expected boundary evidence:

- duration 14076030 s (the immediately preceding 30 s output point): success;
- duration 14076060 s (the next output point): the same DSST mean-conversion non-convergence.

The pinned durations and expected point are regression evidence derived from the first staged reproduction. They are not runtime defaults and must not be promoted into operational configuration.

No convergence epsilon, maximum-iteration value, integrator tolerance, force-model option, or gravity degree/order is changed by this probe.
