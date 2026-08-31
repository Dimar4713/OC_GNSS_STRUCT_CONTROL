# Operational propellant-state coupling

This 0.2.4 increment makes maneuver resource accounting use the current digital-twin spacecraft state instead of silently reverting to passport propellant values.

## Authority

- If `digital_twin.spacecraft_states[*]` exists for a satellite, its `dry_mass_kg` and `current_propellant_mass_kg` are the current mass authority.
- If `digital_twin.spacecraft_states[*].propulsion.isp_s` is explicit, it is the maneuver Isp authority.
- Otherwise the canonical `satellite.spacecraft.isp_s` remains the explicit fallback authority.
- If `propellant_capacity_kg` is known, the configured reserve fraction is reported against capacity; otherwise legacy passport propellant mass remains the reserve basis.

## Maneuver accounting

Maneuvers are processed in time order. For each impulse the current mass before that impulse is used in the Tsiolkovsky mass ratio. The resulting propellant use is subtracted before the next impulse. This matches the existing Orekit sidecar behavior, where `ImpulseManeuver` updates spacecraft mass using the same Isp semantics.

A maneuver that requires more propellant than the currently available amount is rejected fail-closed. Negative residual fuel and mass below dry mass are never accepted.

## Integration boundary

`resolve_operational_satellites()` prepares the spacecraft models that must be placed in `PropagationRequest`. `build_maneuver_resource_rows()` is the preflight/resource-ledger function that must run before propagation. The subsequent integration commit wires these two functions into `run_scenario`; no Java/Orekit force-model or impulse physics is reimplemented in Python.
