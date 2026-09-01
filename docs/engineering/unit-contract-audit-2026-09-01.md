# Unit-contract audit — 2026-09-01

Scope: input adapters → Python DTOs → Java Orekit sidecar → Orekit state/mean conversion → canonical `MeanOrbit` / propagated Cartesian state.

## Confirmed contracts

- Canonical length: metres (`a_m`, `r_m`, `reference_radius_m`).
- Canonical velocity / impulse: m/s (`v_m_s`, `dv_rtn_m_s`).
- Canonical gravitational parameter: m^3/s^2 (`mu_m3_s2`).
- Canonical angular state: radians (`*_rad`, equinoctial `lambda_rad`).
- Canonical angular rate: rad/s where explicitly named (`earth_rotation_rate_rad_s`).
- Canonical time / horizon: seconds (`*_s`, `duration_s`, `output_step_s`).
- Operator osculating UI accepts degrees and converts exactly once with `math.radians()` before the Python→Java boundary.
- Walker UI/application accepts `semi_major_axis_m` and degree inputs and converts angular values exactly once with `math.radians()`.
- Java `MeanConversionEngine` passes `a_m` and radian angles directly to Orekit `KeplerianOrbit`; Orekit outputs SI/radian values into canonical `MeanOrbit`.
- TLE authority delegates raw TLE interpretation to Orekit, avoiding project-side rev/day↔rad/s and km↔m transformations.
- GPS YUMA/SEM runnable authority delegates raw source parsing to Orekit YUMA/SEM parsers, avoiding duplicated project-side unit conversion for authority.

## High-risk boundary found

`glonass-labelled-authority-v1` is an explicit pre-normalized interchange contract. Python and Java do **not** convert its orbital quantities. The values `lambda_rad`, `delta_i_rad`, `argument_of_perigee_rad`, `reference_time_s`, `delta_t_s`, `delta_t_dot`, and time-correction fields are treated as already carrying the exact Orekit constructor semantics.

This means a source supplied in degrees, milliseconds, kilometres, or with a different GLONASS time convention can remain numerically finite and reach Orekit without a dimensional exception. Current range checks protect slot/channel/eccentricity/time-of-day but do not prove the physical unit provenance of angular/time fields.

The engineering GLONASS test fixture assembled from public orbital data is therefore suitable for parser/wire-path testing but must not be used as evidence that the physical GLONASS almanac conversion is validated.

## No gross unit mismatch found in reviewed canonical propagation path

No direct `km→m`, `m→km`, `deg→rad` double conversion, `rad→deg` leakage, `day→s`, or `rev/day→rad/s` conversion defect was found in the reviewed canonical osculating/Walker/MeanOrbit propagation chain.

This does **not** establish physical validation. Remaining validation work must test numerical magnitudes and independent invariants at each conversion boundary.

## Required hardening

1. Add dimensional/magnitude guards for GLONASS authority input, including explicit unit tags in the input schema rather than labels alone.
2. Add conversion-boundary evidence logging: raw value + declared unit + normalized SI/radian value + source epoch/time scale.
3. Add invariant tests for representative GNSS MEO states:
   - semi-major axis magnitude stays in metres;
   - Cartesian radius and velocity magnitudes stay physically plausible;
   - degree→radian conversion occurs exactly once;
   - source→PV→Keplerian round-trip does not introduce 1e3 or 180/pi scale errors;
   - period derived from `a` agrees with propagated phase rate within declared model tolerance.
4. Add GPS/GLONASS/TLE cross-checks against independent Orekit-derived PV at the same epoch/frame.
5. Add explicit time-scale tests for UTC/GPS/GLONASS boundaries and day rollover.
6. Treat any factor close to 1000, 57.2957795, 86400, 2π, or 180 as a unit-contract alarm in validation diagnostics.
