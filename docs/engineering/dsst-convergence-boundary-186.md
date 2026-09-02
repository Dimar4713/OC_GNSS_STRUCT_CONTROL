# DSST mean-conversion convergence boundary — issue #186

This diagnostic is based on the exact engineer-supplied validation scenario preserved in `scenarios/regression/glo_source_linearization_validation_engineer.yaml`.

Observed authoritative Orekit 13.1.7 evidence on the pinned Orekit-data revision:

- 1 day: converges.
- 100 days: converges.
- 1 year: first failure occurs for `GLO-01` at output point 469203, `time_s=14076060`, epoch `2020-06-11T22:01:00Z`.
- failure originates in `FixedPointConverter.convertToMean` called by `DSSTPropagator.computeMeanState` after 201 iterations.

## Fresh-process isolation

The follow-up probe runs each horizon in a separate GitHub Actions job with a newly started Orekit sidecar. Force model, gravity, integrator, 30 s output step, epoch, satellite definitions, Orekit authority, converter epsilon and maximum iteration policy are unchanged.

Fresh-sidecar evidence is deterministic:

- duration `14076030 s`: success; the immediately preceding 30 s output point converges.
- duration `14076060 s`: failure for `GLO-01` at point `469203/469203`, `time_s=14076060`, epoch `2020-06-11T22:01:00Z`, after 201 iterations.
- duration `31536000 s`: failure for the same `GLO-01` state at point `469203/1051201`, `time_s=14076060`, epoch `2020-06-11T22:01:00Z`, after 201 iterations.

This establishes a state-local 30 s convergence boundary for the pinned scenario. The one-year failure is not caused merely by the total requested horizon or output count: a fresh full-year run reaches the same failing state and fails there.

## Cross-request sidecar reuse evidence

An earlier diagnostic executed the staged and boundary requests sequentially against one long-lived sidecar process. In that experiment the nominal `14076030 s` probe failed earlier, at `time_s=13229550`, epoch `2020-06-02T02:52:30Z`.

Because the same `14076030 s` request succeeds in a fresh sidecar process, the earlier result is evidence of cross-request process/state contamination or another request-isolation defect. It is tracked as a separate engineering concern from the deterministic `FixedPointConverter` failure. The exact mutable component responsible has not yet been identified, so this document does not claim a specific cache or Orekit object as the cause.

The pinned durations, timestamps and point index are regression evidence only. They are not runtime defaults and must not be promoted into operational configuration.

No convergence epsilon, maximum-iteration value, integrator tolerance, force-model option, or gravity degree/order is changed by these probes.
