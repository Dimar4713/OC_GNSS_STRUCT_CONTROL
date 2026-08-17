# Scenario schema

Scenarios are YAML validated by pydantic v2 `ScenarioConfig`. No operational constellation parameters are embedded in code; all physical and mission values arrive through configuration.

## Required top-level execution identity

- `scenario_id`;
- `seed`;
- `epoch`;
- `frame` (`EME2000` or `GCRF` for the current Earth-centered Orekit authority);
- `time_scale` (`UTC`, `TAI`, `TT` or `GPS`);
- `duration_s`;
- `output_step_s`.

`ICRF` and `ITRF` exist in the domain vocabulary but the current sidecar rejects them as orbit-propagation frames: ICRF is barycentric and ITRF is non-inertial. ITRF is used internally as the Earth body-fixed frame.

## Force model

`force_model` contains:

- fidelity mode: `screening`, `design` or `validation`;
- configured central-body `mu_m3_s2`;
- Earth ellipsoid `reference_radius_m` and `flattening`;
- J2 and Earth rotation rate for screening/compatibility metadata;
- spherical-harmonic `gravity_degree` and `gravity_order`;
- switches for Moon, Sun, SRP, tides and relativity.

The gravity field loaded by Orekit carries its own reference sphere radius `Ae` and gravitational parameter. The runtime records these provider constants separately from the configured Earth ellipsoid.

## Integrator and constraints

`integrator` declares minimum/maximum step and absolute/relative tolerances. The schema rejects `max_step_s < min_step_s`.

`constraints` contains minimum pair distance, design-element bounds, phase corridor and propellant reserve. `monte_carlo` declares sample count, workers, seed and perturbation sigmas.

## Satellites and mean elements

Each satellite declares:

- `satellite_id`, plane and role;
- `reference_id` for every `additional` spacecraft;
- mean equinoctial state `(a_m, ex, ey, ix, iy, lambda_rad)`;
- mean-element definition (`representation`, theory and force-model fingerprint);
- spacecraft dry/propellant mass, Isp, area and Cr.

The literal fingerprint marker `scenario` is resolved during loading to the SHA-256 of the complete validated force-model configuration. A mean state bound to another fingerprint is rejected.

## Manoeuvres

Optional `maneuvers` is a list of impulsive commands:

```yaml
maneuvers:
  - satellite_id: SYNTH-ADD-45
    time_s: 3600.0
    dv_rtn_m_s: [0.0, 0.05, 0.0]
```

The target must exist and `time_s` must lie inside the scenario duration. The Orekit authority interprets the vector in QSW/RTN coordinates. A manoeuvre at exactly `time_s: 0` is handled explicitly at the initial state; later manoeuvres are event-driven.

## High-fidelity backend selection

For `design` or `validation`, `orekit_sidecar_url` is mandatory at runtime. Its absence is an error; the system never substitutes screening output.

Synthetic examples are provided in:

- `scenarios/orekit_design_smoke.yaml`;
- `scenarios/orekit_validation_smoke.yaml`.

They are CI/development scenarios and are not representations of a specific operational GNSS constellation.
