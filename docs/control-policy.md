# Control policy

## DeadbandController

A manoeuvre is emitted only when the baseline prediction is forecast to leave the phase/safety corridor. Candidate manoeuvres are ranked primarily by safe-horizon length and secondarily by smaller impulse. The controller is not forced to return the state to corridor centre. Any candidate breaching hard minimum distance is rejected.

## Impulsive MPC

`solve_impulsive_mpc` accepts time-varying `A[k]`, `B[k]` and disturbance `d[k]`. No constant HCW/CW matrix is a production authority.

`FiniteDifferenceRoeLinearizationProvider` constructs the matrices locally in D'Amico ROE coordinates by repeatedly calling an authoritative `Propagator`:

- all six state coordinates are central-differenced;
- all three RTN/QSW impulse coordinates are central-differenced;
- each interval is linearized about the propagated mean state at that interval;
- the provider accepts only `ForceMode.VALIDATION` and rejects screening authority;
- scheduled manoeuvres are excluded from the baseline request so the local control derivative is unambiguous.

The inverse D'Amico mapping used for perturbations preserves the reference mean-element definition and force-model fingerprint. Near-equatorial `delta_iy` inversion is rejected when the coordinate mapping becomes ill-conditioned.

The convex MPC objective uses total L1 impulse, a `z` variable bounding cumulative impulse of each spacecraft input slice, tracking error and safety penalties. State corridors, impulse limits and manoeuvre windows are hard constraints.

## Manoeuvre execution semantics

Impulses are expressed as `delta-v_RTN` and mapped through Orekit QSW/RTN geometry. An impulse exactly at the propagation epoch is applied as an explicit osculating-state reset and mass update; later impulses are handled as Orekit events. This distinction is required because an event placed exactly on the initial boundary must not be assumed to fire.

## Receding horizon

Application orchestration applies only the first manoeuvre of an accepted plan, assimilates the new state estimate and solves again. A plan is not granted execution authority until high-fidelity numerical safety replay confirms all hard constraints.

## Required continuation

The next control integration gate is end-to-end coupling of `FiniteDifferenceRoeLinearizationProvider` -> `solve_impulsive_mpc` -> first-manoeuvre numerical replay -> constraint evidence. Monte Carlo shall then perturb state estimation, execution magnitude/direction/time and manoeuvre-window availability around that loop.
