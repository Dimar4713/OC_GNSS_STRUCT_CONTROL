# IAC GLONASS normalized almanac -> Orekit authority bridge

This bridge maps only source/spec semantics that are explicit and reviewed.

## Deterministic mappings

- `reference_date` <- IAC base date (DMV / UTC+3 source convention)
- `reference_time_s` <- `TΩ`
- `lambda_rad` <- `LΩ` degrees converted to radians
- `delta_i_rad` <- `(i - 64.8 deg)` converted to radians
- `eccentricity` <- `e`
- `argument_of_perigee_rad` <- `ω` degrees converted to radians
- `delta_t_s` <- `Tоб - 40544 s`
- `delta_t_dot` <- IAC `ΔT` rate-of-change field
- `frequency_channel` <- `nl`

The nominal inclination `64.8 deg` and nominal draconian period `40544 s` are GLONASS almanac specification constants, not operator-tuned defaults.

## Mandatory supplementary authority

The IAC table does not provide all fields required by the existing Orekit `GLONASSAlmanac` authority contract. The bridge therefore requires explicit supplementary values for:

- health;
- GLONASS-to-UTC correction;
- GPS-to-GLONASS correction;
- GLONASS-system time offset used by the Orekit authority contract.

No zero/default values are inserted silently.

The IAC `δt2` field is preserved in the normalized source as the source-declared onboard clock correction, but is **not** silently substituted for any of the three Orekit time-correction fields. A reviewed sign/semantic equivalence is required before such a mapping can be introduced.

This bridge produces a `GlonassAuthorityRecord`; it does not itself execute propagation or create/overwrite a scenario. The existing Orekit GLONASS analytical propagation -> DSST mean pipeline remains the numerical authority path.
