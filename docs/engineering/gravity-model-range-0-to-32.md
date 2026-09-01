# Gravity model range contract — Kepler to EIGEN-6S 32x32

Operator requirement: the scenario and Preview UI must allow an explicit Earth-gravity fidelity selection from a simple Kepler model through EIGEN-6S degree/order 32x32.

Contract:
- `gravity_degree=0`, `gravity_order=0`: Kepler/central-body baseline. No spherical-harmonic perturbation force is added in DSST; numerical propagation must retain central attraction through the Orekit propagator's central attraction authority.
- `gravity_degree=2`, `gravity_order=0`: J2-class zonal model using the degree-2 EIGEN-6S coefficient authority.
- `gravity_degree=N`, `gravity_order=M`, `2 <= N <= 32`, `0 <= M <= N`: EIGEN-6S spherical harmonics truncated at the requested degree/order.
- Full models such as 4x4, 8x8, 12x12, 16x16, 24x24 and 32x32 are UI presets, not separate physics implementations.
- `gravity_order > gravity_degree` or either value above 32 fails closed.
- Gravity degree/order remain part of the force-model fingerprint and therefore change scenario/config authority identity.
- Existing moon/sun/SRP switches are independent of the Earth-gravity truncation and remain explicit scenario settings.

Validation use:
For model adequacy investigations, compare the same initial state and horizon under 0x0, 2x0, 4x4, 8x8, 16x16 and 32x32. Convergence of the operational drift metric should be reported, not assumed.
