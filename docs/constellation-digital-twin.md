# Constellation digital-twin foundation

Status: first backward-compatible domain slice after Engineering Preview 0.2.3.

## Boundary

The digital-twin layer is an operator/input and state-model extension around the existing authoritative scenario and propagation pipeline. It does not change force-model authority, frames, time scales, mean-element semantics, integrator settings or Orekit selection.

Legacy Preview 0.2 scenarios remain valid when `digital_twin` is absent. The optional block is removed from `ScenarioConfig.config_hash()` when absent so historical hashes remain compatible.

## Existing canonical objects reused

- `ScenarioConfig` remains the scenario root.
- `ConstellationSpec` / `SatelliteSpec` remain the canonical constellation membership and orbit definition.
- `SpacecraftModel` remains the legacy propagation-facing spacecraft model.
- `MonteCarloConfig` remains the existing robustness/Monte-Carlo configuration.

No parallel scenario schema is introduced.

## New optional `digital_twin` block

`DigitalTwinConfig` adds operational state and experiment provenance that engineers need without forcing those fields into old scenarios.

### Spacecraft operational state

Per spacecraft:

- `satellite_id`;
- optional `spacecraft_model_id`;
- dry mass;
- current propellant mass;
- optional propellant capacity;
- optional explicit current mass;
- optional propulsion-system metadata;
- optional correction-system metadata.

When current mass is provided it must equal dry mass plus current propellant mass. If omitted it is derived from those two values.

### Groups

`SpacecraftGroup` supports explicit engineer-defined groups such as "5 spacecraft type 1" and "10 spacecraft type 2". Group membership is a set of existing `satellite_id` values and is validated fail-closed.

### Perturbations

`PerturbationRule` is explicit and deterministic metadata for the planned Perturbation Designer UI.

Supported first-slice scopes:

- whole constellation;
- orbital plane;
- engineer-defined group;
- individual spacecraft.

Supported first-slice distributions:

- Gaussian: explicit mean and sigma;
- Uniform: explicit lower and upper bounds.

No hidden sigma, bounds or target defaults are introduced. Non-constellation scopes require explicit targets. Targets are checked against the scenario constellation, plane ids or declared groups.

### Lineage

`ScenarioLineage` records the immediate parent scenario id/hash and transformation class. Perturbation-derived scenarios may also record the random seed. The source scenario remains immutable; UI/import/save work must create a new scenario file.

## Next implementation slices

1. XLS/XLSX import with column mapping and a dedicated current-mass / remaining-propellant table.
2. Osculating-element and Walker input adapters.
3. Perturbation Designer operator panel with mean/standard-deviation controls, group assignment and individual overrides.
4. Derived-scenario save workflow with parent hash and perturbation metadata.
5. GNSS almanac, NORAD TLE/OMM and RINEX adapters.
6. Maneuver-driven propellant consumption and current-mass evolution.

## Numerical-authority invariant

The operator conveniences above prepare validated inputs. They do not constitute design or validation authority by themselves. Existing screening/design/validation authority labels and Orekit fail-closed behavior remain unchanged.
