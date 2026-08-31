# Walker constellation engineering input

The Walker generator is an engineering input adapter for creating a new constellation definition from an existing validated scenario. It never overwrites the parent scenario.

## Walker Delta parameters

- `T` / `total_satellites`: total spacecraft count.
- `P` / `planes`: number of equally populated orbital planes.
- `F` / `phasing`: Walker inter-plane phasing integer, `0 <= F < T`.
- semi-major axis, eccentricity and inclination define the common project orbit.
- `raan0_deg` is the RAAN of plane 1.
- `mean_anomaly0_deg` is the phase of slot 1 in plane 1.
- a selected template spacecraft supplies the existing validated `SpacecraftModel` (mass, propellant, Isp, area, Cr).

For plane index `j` and in-plane slot `k`:

- `RAAN(j) = RAAN0 + 360*j/P` degrees;
- `M(j,k) = M0 + 360*k/(T/P) + 360*F*j/T` degrees.

`T` must be divisible by `P`; otherwise generation fails closed.

## Canonical representation

The current computational scenario stores mean equinoctial elements. Walker project geometry is therefore written explicitly as `walker-delta-engineering-mean-input`, with the parent force-model fingerprint attached to the mean-element definition.

No osculating state is silently re-labelled as a mean state.

## Derived-scenario rules

Walker generation creates a new YAML with:

- a new `scenario_id`;
- a new constellation and plane inventory;
- the selected template spacecraft model copied to generated spacecraft;
- old maneuvers cleared because they reference the parent spacecraft inventory;
- `digital_twin.lineage.parent_scenario_id`;
- `digital_twin.lineage.parent_config_hash`;
- `digital_twin.lineage.transformation = walker_generation`.

Existing target files are never overwritten.

## Osculating input boundary

Direct engineering input of osculating Keplerian elements is a separate adapter. The current canonical scenario consumes mean equinoctial elements, so an osculating input must pass through an explicit reviewed osculating-to-mean conversion authority (Orekit for high-fidelity modes) before it can become canonical scenario state. The UI must fail closed rather than treating osculating elements as mean elements.
