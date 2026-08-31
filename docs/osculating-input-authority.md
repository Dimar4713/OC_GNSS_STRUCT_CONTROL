# Osculating input authority

Engineering users may provide Keplerian osculating elements as `(a, e, i, omega, RAAN, anomaly)` together with epoch, frame, time scale and anomaly type.

## Authority rule

Osculating elements are never relabelled as `MeanOrbit` and no Python approximation is permitted as a hidden fallback.

The conversion path is:

`Keplerian osculating input -> Orekit 13.1.7 sidecar -> DSST computeMeanState -> canonical equinoctial MeanOrbit`.

The endpoint is `POST /v1/orbits/osculating-to-mean` on the loopback-bound Orekit sidecar.

The request carries the exact force model, spacecraft model and force-model fingerprint. The result is accepted only when it identifies:

- backend `orekit-dsst-mean-conversion`;
- Orekit version;
- pinned Orekit-data physical SHA-256;
- requested gravity authority;
- the same force-model fingerprint in `MeanElementDefinition`.

Unsupported force configurations that cannot produce the same DSST mean definition fail closed. There is no local fallback.

## Representation

Input:
- semi-major axis `a_m`;
- eccentricity `e`;
- inclination `i_rad`;
- argument of perigee `pa_rad`;
- right ascension of ascending node `raan_rad`;
- anomaly `anomaly_rad`;
- anomaly type: `mean`, `eccentric`, or `true`.

Output is the existing canonical `MeanOrbit(a_m, ex, ey, ix, iy, lambda_rad)` with theory `orekit-dsst-13.1.7-from-osculating`.

## Preview integration

The operator UI must use this conversion gate before creating a derived scenario from osculating inputs. If the sidecar is unavailable, stale, mismatched, or returns incomplete provenance, scenario creation is rejected.
