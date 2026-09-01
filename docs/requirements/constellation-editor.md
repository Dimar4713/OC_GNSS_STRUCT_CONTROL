# Constellation editor requirements

## Operator need

Engineering scenarios must support explicit editing of constellation membership without hand-editing YAML.

Required operations:

1. Add spacecraft to the selected scenario.
2. Remove spacecraft from the selected scenario.
3. Edit spacecraft identity and parameters.
4. Move spacecraft between orbital planes.
5. Maintain digital-twin group membership consistently.
6. Preview all structural consequences before creating a derived scenario.

## Safety and lineage contract

- The source scenario YAML is immutable.
- Every accepted edit creates a new derived scenario with a new `scenario_id` and new YAML filename.
- Existing target YAML is never overwritten.
- `satellite_id` values remain unique.
- Plane membership must remain consistent between `SatelliteSpec.plane_id` and `ConstellationSpec.planes[].satellite_ids`.
- Removing or renaming a spacecraft must fail closed while it is referenced by maneuvers, `reference_id`, digital-twin operational state, groups, satellite-scoped perturbations, or other scenario structures unless the operator explicitly resolves those references in the same edit transaction.
- Removing a reference spacecraft must fail closed while `additional` spacecraft reference it unless references are reassigned explicitly.
- Editing orbital elements must preserve the canonical mean-element authority contract. Osculating inputs require the reviewed Orekit osculating-to-mean path before promotion.
- Mass/fuel/Isp and spacecraft physical parameters remain explicit numerical authority and are never silently copied from unrelated spacecraft.
- A structural edit must persist lineage with parent scenario id/hash and transformation `constellation_editor`.

## UI contract

The operator surface shall provide a spacecraft table with selection and explicit actions:

- `Добавить КА / Add spacecraft`
- `Редактировать / Edit`
- `Удалить / Remove`
- `Переместить в плоскость / Move to plane`
- multi-select for batch removal/move where safe

For each spacecraft the editor must expose, at minimum:

- `satellite_id`
- `plane_id`
- role (`reference` / `additional`)
- `reference_id` when required
- canonical mean-orbit parameters with units and authority indication
- spacecraft dry mass, propellant mass, Isp, area and Cr
- digital-twin group memberships and operational resource state when present

Before save, show a diff/preview with added, removed, renamed, moved and changed spacecraft plus affected references/groups/maneuvers.

## Relationship to GNSS/NORAD import

Importers must use the same structural editing core rather than directly replacing an arbitrary existing spacecraft. GPS/GLONASS/TLE imports may add new spacecraft or update only an explicitly mapped existing spacecraft. This prevents cross-constellation identity corruption such as assigning GPS orbital data to `GLO-01` while retaining the GLONASS identity.
