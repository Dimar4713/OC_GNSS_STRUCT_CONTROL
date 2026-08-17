# High-fidelity robustness campaign

## Purpose

The robustness campaign quantifies how an already accepted constellation design/control candidate behaves under configured uncertainty. It is not a substitute for design search or maneuver authorization. Final robustness claims are produced only from the numerical Orekit validation backend with exact force-model/data authority.

## Authority boundary

A final campaign requires:

- scenario force mode `validation`;
- backend identity beginning with `orekit-numerical`;
- exact force-model fingerprint match;
- configured gravity authority (`EIGEN-6S` in the current contour);
- exact Orekit runtime version;
- exact reviewed orekit-data revision and physical SHA-256.

Screening or DSST results cannot satisfy final robustness authority. A mismatch aborts the realization rather than silently falling back.

## Reproducibility and parallelism

All random samples are generated in deterministic realization order **before** worker dispatch. The worker count therefore cannot affect random draws, sample hashes or aggregate statistics.

Each realization stores:

- realization index;
- realization seed;
- full sampled uncertainty vector;
- sample SHA-256;
- outcome and violated constraints;
- campaign configuration hash.

Bounded `ThreadPoolExecutor` parallelism is used only after samples are fixed.

## Resumability

Each realization is written under `realizations/NNNNNN/` as `sample.json` and `outcome.json`.

A realization may be reused only when both files exist and:

- the saved sample SHA-256 matches the newly generated sample;
- the saved campaign hash matches the current campaign configuration.

Partial or mismatched state fails closed. The system never guesses whether an old realization is compatible.

## Supported uncertainty naming contract

Unknown names are rejected before sampling so a YAML typo cannot silently remove an uncertainty source.

For a spacecraft `<SAT>`:

- injection / initial mean-state errors:
  - `initial.<SAT>.delta_a_m`
  - `initial.<SAT>.delta_ex`
  - `initial.<SAT>.delta_ey`
  - `initial.<SAT>.delta_ix`
  - `initial.<SAT>.delta_iy`
  - `initial.<SAT>.delta_lambda_rad`
- orbit-determination mean-state errors use the same suffixes under `od.<SAT>.*`;
- initial slot separation error: `slot.<SAT>.delta_lambda_rad`;
- SRP coefficient-product uncertainty: `spacecraft.<SAT>.cr_area_over_mass_fraction`.

The last variable is interpreted as a fractional change in `Cr*A/m`. The current spacecraft model keeps `A/m` fixed and realizes that fractional product uncertainty through `Cr`.

For baseline maneuver index `<N>`:

- `maneuver.<N>.magnitude_fraction`;
- `maneuver.<N>.direction_r_rad`;
- `maneuver.<N>.direction_t_rad`;
- `maneuver.<N>.direction_n_rad`;
- `maneuver.<N>.timing_error_s`;
- `window.<N>.unavailable`.

Window availability is Boolean and must use a Bernoulli distribution. Bernoulli distributions are rejected for numeric uncertainty variables. Window variables cannot be placed inside correlated normal groups.

## Distributions and correlations

Scalar variables support:

- Normal (`mean`, `sigma`);
- Uniform (`low`, `high`);
- Bernoulli (`probability_true`).

Correlated normal groups accept a vector of variable names, optional mean vector and full covariance matrix. Covariance is validated for shape, finiteness, symmetry and positive semidefiniteness before any sampling.

This supports orbit-determination covariance without hard-coding operational covariance values in source code.

## Maneuver perturbations

Magnitude error scales the nominal RTN impulse. Small direction errors are applied with the first-order rotation approximation

`dv_perturbed = scale * dv_nominal + rotation_error × dv_nominal`.

Timing error shifts the maneuver epoch. A maneuver is explicitly marked dropped when its availability window is unavailable or the sampled epoch falls outside the propagation horizon.

## Metrics and violations

Every numerical outcome includes at least:

- total fleet delta-V;
- total propellant used;
- per-spacecraft delta-V;
- per-spacecraft propellant used and residual propellant;
- required reserve;
- estimated time to reserve exhaustion when a finite estimate exists;
- minimum pair distance across all spacecraft pairs;
- maximum relative phase, eccentricity-vector and inclination-vector excursions;
- minimum delta-a corridor margin;
- exact numerical backend provenance;
- hard/soft violation flags.

Violation probabilities are reported for minimum distance, phase, delta-a, eccentricity, inclination, propellant reserve and maneuver-window availability.

## Lifetime estimate semantics

`reserve_lifetime_estimate_s` is a **linear extrapolation** from propellant used during the configured campaign horizon:

`horizon * usable_propellant_to_reserve / propellant_used_on_horizon`.

It is an engineering screening estimate of time to the configured reserve under repeated comparable expenditure. It is not a guarantee of spacecraft lifetime and does not model future changes in maneuver cadence, environment, failures or operations unless those effects are explicitly represented in the campaign.

Realizations with zero propellant expenditure have no finite depletion estimate (`null`). Aggregate lifetime percentiles are calculated over the realizations that produce finite estimates, and the report records their count.

## Statistics and artifacts

The campaign emits:

- `campaign_manifest.json` with campaign/application/scenario lineage and accepted candidate/control plan;
- `samples.csv` and `samples.parquet`;
- `outcomes.csv` and `outcomes.parquet`;
- per-realization sample/outcome JSON;
- `summary.json`;
- `statistics.csv` with count, P50, P95, P99 and worst values;
- `violation_probability.csv`;
- `report.md` and `report.html` with distribution and violation tables.

The configured worst metric must be finite in every realization. Worst-case evidence identifies the exact realization and preserves its full outcome.

## Physics invariant

Instantaneous osculating semi-major axis is never used as the secular-drift criterion. Relative stability checks continue to use force-model-consistent mean-element histories and D'Amico ROE. Cartesian states are used for physical pair-distance safety, not as a substitute for mean-element secular drift analysis.
