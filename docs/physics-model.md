# Physics model

## Screening
The fast backend propagates force-model-consistent mean elements with two-body mean motion and first-order J2 secular rates:

- `n = sqrt(mu/a^3)`
- `p = a(1-e^2)`
- `Omega_dot = -3/2 J2 n (R/p)^2 cos(i)`
- `omega_dot = 3/4 J2 n (R/p)^2 (5 cos^2(i)-1)`
- `M_dot = n + 3/4 J2 n (R/p)^2 sqrt(1-e^2)(3 cos^2(i)-1)`

This level is for screening and Δa-zero search only.

## Design
The intended authoritative backend is Orekit DSST with configurable zonal/tesseral harmonics, Sun, Moon and SRP, plus a documented mean↔osculating theory under the same force set.

## Validation
The numerical reference uses Cartesian propagation with configured gravity degree/order, differential third-body terms, SRP/eclipse and manoeuvres. Tides and relativity are scenario switches.

## Relative state
For deputy/reference pairs the control state is D'Amico ROE. Relative longitude is exactly

`delta_lambda = delta_M + delta_omega + cos(i_ref) * delta_Omega`.

## Drift estimator
Relative longitude is unwrapped and fitted by harmonic regression: intercept + secular slope + sinusoidal/cosinusoidal components. The basis includes orbital, sidereal-day/tesseral, lunar and sidereal-year frequencies. The fitted linear coefficient is the secular drift estimate. Endpoint differencing alone is not accepted as drift evidence.
