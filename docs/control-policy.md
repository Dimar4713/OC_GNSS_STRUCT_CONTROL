# Control policy

## DeadbandController
A manoeuvre is emitted only when the baseline prediction is forecast to leave the phase/safety corridor. Candidate manoeuvres are ranked primarily by the safe-horizon length and secondarily by smaller impulse. The controller is not forced to return the state to corridor centre. Any candidate breaching hard minimum distance is rejected.

## Impulsive MPC
`solve_impulsive_mpc` accepts time-varying `A[k]`, `B[k]` and disturbance `d[k]`. Matrices are inputs from a numerical variational-equation/finite-difference provider; no constant dynamics matrices are hardcoded.

The convex objective uses total L1 impulse, a `z` variable bounding cumulative impulse of each spacecraft input slice, and tracking error. State corridors, impulse limits and manoeuvre windows are hard constraints.

## Receding horizon
Application orchestration shall apply only the first planned manoeuvre, assimilate the new state estimate and solve again. High-fidelity safety validation after each solve is mandatory before execution authority is granted.
