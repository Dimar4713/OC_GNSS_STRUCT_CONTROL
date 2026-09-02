# DSST mean-conversion convergence boundary — issue #186

This diagnostic is based on the exact engineer-supplied validation scenario preserved in `scenarios/regression/glo_source_linearization_validation_engineer.yaml`.

Observed authoritative Orekit 13.1.7 evidence on the pinned Orekit-data revision:

- 1 day: converges.
- 100 days: converges.
- 1 year: first failure occurs for `GLO-01` at output point 469203, `time_s=14076060`, epoch `2020-06-11T22:01:00Z`.
- failure originates in `FixedPointConverter.convertToMean` called by `DSSTPropagator.computeMeanState` after 201 iterations.

## Fresh-process isolation and satellite separation

Each probe runs in a separate GitHub Actions job with a newly started Orekit sidecar. Force model, gravity, integrator, 30 s output step, epoch, satellite definitions, Orekit authority, converter epsilon and maximum iteration policy are unchanged.

A full two-satellite scenario cannot be used to prove that the point immediately before the `GLO-01` boundary is globally successful, because the second satellite has its own earlier DSST mean-conversion failure. The reproducer therefore supports a diagnostic-only satellite filter, preserving the selected satellite's original state and force model.

Fresh-sidecar evidence:

- `GLO-01` only, duration `14076030 s`: success. The reference satellite converges through the immediately preceding 30 s point.
- `GLO-01` only, duration `14076060 s`: failure at point `469203/469203`, `time_s=14076060`, epoch `2020-06-11T22:01:00Z`, after 201 iterations.
- full two-satellite scenario, duration `14076030 s`: `GLO-01` completes, then `GLO-LIN-DEP` fails at point `442199/469202`, `time_s=13265940`, epoch `2020-06-02T12:59:00Z`, after 201 iterations.
- full two-satellite scenario, duration `31536000 s`: execution stops first on `GLO-01` at point `469203/1051201`, `time_s=14076060`, epoch `2020-06-11T22:01:00Z`, after 201 iterations, so the later processing of `GLO-LIN-DEP` is not reached in that request.

This establishes two distinct state-local DSST mean-conversion non-convergence cases in the engineer scenario. It also retracts the earlier interpretation that the June 2 failure was evidence of cross-request sidecar contamination: fresh-process evidence now shows that the June 2 failure belongs to `GLO-LIN-DEP` itself.

No memory leak, cache contamination, or request-isolation defect is established by the current evidence. Those hypotheses should not be treated as active findings unless a dedicated same-input A/B reuse test demonstrates request-history dependence.

The pinned durations, timestamps and point indexes are regression evidence only. They are not runtime defaults and must not be promoted into operational configuration.

No convergence epsilon, maximum-iteration value, integrator tolerance, force-model option, or gravity degree/order is changed by these probes.
