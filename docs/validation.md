# Validation and acceptance

Validation evidence is separated by fidelity authority. A green lower-fidelity gate must never be presented as evidence for a higher-fidelity claim.

## Screening evidence

The in-process synthetic backend is used only for fast screening and unit tests. Automated evidence covers:

- two-body/J2=0 mean-motion consistency with analytic Kepler motion;
- first-order J2 secular-rate recovery from propagated mean-element histories;
- identical mean orbits with phase offset preserving zero relative secular drift;
- harmonic regression recovering an injected secular slope;
- physically valid symmetry cases;
- fuel accounting, deadband safety, deterministic Monte Carlo and end-to-end artifact generation.

## Design authority: Orekit DSST

`sidecar/orekit-service` implements the design authority with Orekit 13.1.7. The DSST path supports configured zonal gravity, tesseral gravity when order > 0, Moon, Sun and SRP. Input and output mean elements remain DSST/force-model consistent. Cartesian output is generated from DSST mean states using the same force set.

The service fails closed for unsupported combinations. In particular, tides are currently rejected, and relativity is not claimed for the DSST design authority.

## Validation authority: Orekit numerical propagation

The numerical authority propagates Cartesian osculating states using configured spherical harmonics, third-body Moon/Sun, SRP with Earth shadow geometry, optional relativity and impulsive RTN/QSW manoeuvres. Initial mean states are converted to osculating states with DSST using the same mean-force family; numerical output is converted back to DSST-consistent mean elements before drift metrics are computed.

Initial impulses at exactly the scenario epoch are applied as an explicit state reset rather than relying on a date event at the initial propagation boundary. Later impulses remain event-driven. Propellant mass is updated with the rocket equation.

## Reproducibility evidence

High-fidelity CI fetches the official `orekit-data` repository at the pinned revision:

```text
f395924f27b6074c8db1432350f5917d722ff3e1
```

The sidecar hashes the complete loaded data directory and returns `orekit_data_sha256`. Results also record Orekit version, frame, time scale, gravity degree/order, gravity-provider `mu` and `Ae`, Earth ellipsoid radius/flattening and force-model fingerprint.

The gravity model's reference sphere radius `Ae` is intentionally distinguished from the Earth ellipsoid equatorial radius; they are different physical/model parameters.

## Mean/osculating and control gates

Automated high-fidelity tests enforce:

1. DSST design execution with real Orekit auxiliary data.
2. Numerical validation execution with the same pinned data authority.
3. Mean -> osculating -> mean round-trip within declared component tolerances.
4. Moon/Sun/SRP execution in both high-fidelity authority modes.
5. RTN/QSW impulsive manoeuvre effect on propagated mean orbit.
6. Finite-difference recovery of time-varying `A[k]`, `B[k]`, `d[k]` in D'Amico ROE coordinates.
7. Rejection of screening authority as a source of MPC linearization matrices.
8. Top-K design replay that accepts only an `orekit-numerical*` validation backend and requires an explicit ranking policy.

`delta_lambda` and relative RAAN secular rates are estimated from propagated, force-model-consistent mean histories. Instantaneous osculating semi-major axis is never a secular-drift criterion.

## Remaining validation work

- wire full optimisation orchestration into top-K numerical replay and engineering reports;
- add end-to-end post-MPC numerical safety replay for every accepted manoeuvre plan;
- extend Monte Carlo sources to injection, OD, manoeuvre magnitude/direction/time, `Cr*A/m` and manoeuvre-window availability;
- add tides only when a scenario requires them and validate the exact Orekit tide model/data contract;
- qualify operational scenarios and force-model/data revisions separately from the synthetic CI scenarios.
