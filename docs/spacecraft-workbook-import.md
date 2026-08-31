# Spacecraft workbook import

The engineer workbook is a convenience/input adapter. The canonical model remains `ScenarioConfig` + optional `DigitalTwinConfig`; workbook values are validated before they can become scenario state.

Supported file extensions: `.xlsx` and legacy `.xls`.

## Required sheet: `Spacecraft_State`

One row describes the current operational state of one spacecraft.

Required columns:

| Column | Meaning |
| --- | --- |
| `satellite_id` | Spacecraft identifier already used by the constellation scenario |
| `dry_mass_kg` | Dry mass, kg |
| `current_propellant_mass_kg` | Remaining propellant at the state epoch, kg |

Optional columns:

| Column | Meaning |
| --- | --- |
| `spacecraft_model_id` | Engineer-defined spacecraft model/type |
| `propellant_capacity_kg` | Declared propellant capacity, kg |
| `current_mass_kg` | Current total mass; if present it must equal dry mass + current propellant |
| `propulsion_system_type` | Propulsion system type |
| `propulsion_model_id` | Propulsion model identifier |
| `thrust_n` | Thrust, N |
| `isp_s` | Specific impulse, s |
| `propellant_type` | Propellant type |
| `correction_system_type` | Orbit-correction system type |
| `correction_mode` | `ground`, `autonomous`, or `hybrid` |

No physical defaults are invented. For example, `isp_s` without an explicit `propulsion_system_type` is rejected.

## Optional sheet: `Spacecraft_Groups`

Use this sheet for engineer-defined group requirements such as “5 spacecraft type 1, 10 spacecraft type 2”. Each row adds one spacecraft to a group.

Required columns:

| Column | Meaning |
| --- | --- |
| `group_id` | Group identifier |
| `satellite_id` | Group member spacecraft |

Example:

| group_id | satellite_id |
| --- | --- |
| TYPE_1 | G01 |
| TYPE_1 | G02 |
| TYPE_2 | G06 |

The resulting groups can later be selected directly in the Perturbation Designer.

## Validation rules

- remaining propellant must be non-negative;
- remaining propellant must not exceed declared capacity;
- dry mass must be positive;
- if current mass is supplied, it must equal dry mass + remaining propellant;
- duplicate spacecraft state rows are rejected by `DigitalTwinConfig`;
- group membership and spacecraft IDs are additionally checked against the canonical `ScenarioConfig` when the imported block is attached to a scenario.

## Planned operator flow

`Select XLS/XLSX → preview rows → validation report → column mapping (later adapter slice) → attach to scenario → save as new/derived scenario`.

Source scenarios are never overwritten by the import operation.
