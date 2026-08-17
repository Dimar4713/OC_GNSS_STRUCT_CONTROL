# MPC execution authority

## Decision boundary

Solving the convex impulsive MPC problem does **not** authorize a spacecraft maneuver. The optimizer may propose a plan; execution authority is granted only after the exact first RTN impulse is replayed through the authoritative numerical Orekit validation backend and all hard checks pass.

This separation is intentional: a locally linear model is useful for optimization, but it is not sufficient evidence for a nonlinear safety decision.

## State and control contract

The MPC state uses D'Amico relative orbital elements in the fixed order:

`[delta_a, delta_lambda, delta_ex, delta_ey, delta_ix, delta_iy]`.

`delta_a` is normalized by the reference mean semi-major axis. The control is an impulsive RTN/QSW velocity increment `[dV_R, dV_T, dV_N]` in m/s.

Every receding-horizon authority call derives fresh time-varying `A[k]`, `B[k]` and `d[k]` matrices with `FiniteDifferenceRoeLinearizationProvider` using the validation propagator. The execution layer does not reuse stale matrices between authority decisions.

## Convex planning constraints

The CVXPY problem enforces:

- component-wise ROE lower/upper bounds;
- phase corridor;
- second-order-cone bounds on the relative eccentricity vector;
- second-order-cone bounds on the relative inclination vector;
- RTN component impulse limits;
- configured maneuver windows;
- the balancing variable `z` over spacecraft input slices.

Minimum impulse bit and nonlinear pair-distance safety are intentionally not approximated as convex objective penalties. They are checked by the execution-authority layer.

## First-maneuver rule

Only the first impulse of a solved horizon may be considered for execution. Future impulses remain planning information. Before another maneuver decision, the state estimate is updated and the system must re-linearize and re-plan.

Every `ManeuverAuthorityEvidence` therefore carries `requires_relinearization = true`.

## Pre-replay gates

Before spending a numerical replay, the proposed first maneuver must pass:

1. nonzero-command check;
2. minimum impulse bit for each commanded nonzero RTN component;
3. Tsiolkovsky propellant calculation;
4. residual propellant reserve check.

A failure at this layer yields no execution authority and no attempt to disguise the rejected command as an accepted maneuver.

## Numerical replay authority

The exact first RTN impulse is inserted at `t = 0` into the baseline request and replayed. A maneuver can be authorized only when the replay:

- identifies itself as `orekit-numerical*`;
- returns the same force-model fingerprint as the request;
- returns the configured gravity authority (`EIGEN-6S` in the current high-fidelity contour);
- records Orekit version, reviewed orekit-data revision and physical data SHA-256;
- returns the requested time grid.

Screening and DSST design identities are explicitly insufficient for execution authority.

## Nonlinear safety checks

The numerical trajectory is checked over the replay horizon for:

- physical `delta_a` corridor derived from mean ROE and reference mean semi-major axis;
- `delta_lambda` phase corridor;
- relative eccentricity-vector norm;
- relative inclination-vector norm;
- minimum Cartesian distance over **all spacecraft pairs** and all replay epochs.

The current controller instance controls one configured additional spacecraft/reference pair, while fleet separation safety is evaluated against every spacecraft included in the propagation request.

## Linear-model trust gate

The first numerical replay state is converted back to D'Amico ROE and compared with the MPC-predicted next state. Phase error is wrapped to `[-pi, pi]` before comparison.

Each ROE component has an explicit positive trust tolerance. The normalized error is

`max_i(abs(x_replay[i] - x_linear[i]) / tolerance[i])`.

Execution authority is rejected when this ratio exceeds `1.0`. A rejection requires re-linearization/re-planning rather than widening tolerances implicitly.

## Evidence

The authority record preserves:

- full `A[k]`, `B[k]`, `d[k]`;
- MPC state and impulse trajectories;
- objective value;
- exact first maneuver;
- numerical replay next-state ROE;
- trust-error ratio;
- fleet minimum pair distance;
- propellant used, remaining propellant and required reserve;
- replay backend and authority provenance;
- authorization decision and reason.

The CI real-Orekit acceptance writes both JSON and compressed NPZ evidence. These files are part of the retained high-fidelity diagnostics artifact.

## Scope and non-claims

This layer provides software-side maneuver **authorization evidence**. It is not a spacecraft command uplink, flight-procedure approval, or operational command-and-control interface.

The secular-drift invariant remains unchanged: instantaneous osculating semi-major axis is never used as a secular-drift criterion. Drift and control state reasoning remain tied to force-model-consistent mean-element histories.
