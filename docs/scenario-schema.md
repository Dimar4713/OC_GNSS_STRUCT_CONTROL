# Scenario schema

Scenarios are YAML validated by pydantic v2 `ScenarioConfig`.

Required top-level identity/execution fields: `scenario_id`, `seed`, `epoch`, `duration_s`, `output_step_s`.

`force_model` contains fidelity mode, central-body gravitational parameter, reference radius, J2, rotation rate, gravity degree/order and perturbation switches. `integrator` contains step and tolerance policy even when screening does not consume every field; this keeps manifests comparable across fidelity levels.

`constraints` contains minimum distance, design-element bounds, phase corridor and propellant reserve. `monte_carlo` declares sample count, workers, seed and perturbation sigmas.

Each satellite declares role, plane, mean equinoctial state, mean-element definition and spacecraft parameters. Every `additional` satellite must name a valid `reference_id`.

For `design` or `validation`, `orekit_sidecar_url` is mandatory at runtime. Its absence is an error; the system never substitutes screening output.
