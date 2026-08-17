# Mean and osculating elements

## Invariant
Mean elements are not merely a smoothing of arbitrary osculating outputs. They are model-dependent quantities. A value is usable for drift comparison only when its `MeanElementDefinition` identifies the generating theory and the force-model fingerprint.

## Storage
`MeanOrbit` stores equinoctial-style components `(a, ex, ey, ix, iy, lambda)` to avoid singular behaviour near circular or low-inclination regimes.

## Screening conversion
The MVP converts this representation to classical mean elements only to evaluate the analytic J2 rates and then reconstructs the same mean definition.

## High-fidelity round trip
Orekit design/validation must implement and test `mean -> osculating -> mean` under an unchanged force model. The accepted tolerance must be stated in the validation configuration and report. This is tracked in #6 and is a blocking gate for claiming high-fidelity design equivalence.

## Forbidden shortcut
Instantaneous osculating semi-major-axis oscillations must not be used to infer secular relative phase drift or to drive design optimisation.
