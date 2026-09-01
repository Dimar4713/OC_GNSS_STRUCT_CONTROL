# IAC GNSS online/offline intake

Engineering Preview accepts GNSS source tables from the Information and Analysis Center (`glonass-iac.ru`) in two equivalent intake modes:

- online fetch from a fixed allowlist of project-reviewed IAC data sources;
- offline import of a saved TXT/TSV/semicolon-delimited table for the same dataset.

Supported public pages:

- GLONASS almanac — `https://glonass-iac.ru/glonass/ephemeris/`;
- GPS almanac — `https://glonass-iac.ru/gps/ephemeris/`;
- BeiDou almanac — `https://glonass-iac.ru/beidou/ephemeris/`;
- BeiDou constellation composition — `https://glonass-iac.ru/beidou/sostavOG/`.

## Verified online source contract

A read-only live probe was executed on `aimeton-main-server` through the canonical `infra-control` self-hosted lane on 2026-09-01. The ephemeris pages are dynamic and do not contain their displayed almanac as a static HTML table. The verified data endpoints are therefore used directly:

- GLONASS — `https://glonass-iac.ru/glonass/ephemeris/ephemeris_json.php`;
- GPS — `https://glonass-iac.ru/gps/ephemeris/ephemeris_json.php`;
- BeiDou — `https://glonass-iac.ru/beidou/ephemeris/beidou_almanac_calc.php`;
- BeiDou constellation composition remains the static detailed table on `https://glonass-iac.ru/beidou/sostavOG/`.

Observed live inventories during contract verification were 24 GLONASS records, 32 GPS records and 60 BeiDou almanac records plus a BeiDou source-date marker. These counts are evidence from that retrieval, not hardcoded acceptance limits: operational constellation membership may change.

Verified GLONASS fields are `ns`, `datetime`, `Tomega`, `Tapp`, `e`, `i`, `Lomega`, `W`, `deltaT2`, `nl`, `deltaT`. They are emitted as canonical columns `NS, Дата, TΩ, Tоб, e, i, LΩ, ω, δt2, nl, ΔT`.

Verified GPS fields are `PRN`, `datetime`, `t`, `e`, `i`, `DomegaDT`, `A`, `Lomega`, `w`, `mm`, `af0`, `af1`. The live source currently uses decimal comma in many numeric strings; intake preserves the source representation rather than silently changing units or locale.

Verified BeiDou almanac fields are `ID`, `Health`, `Eccentricity`, `Time of Applicability(s)`, `Orbital Inclination(rad)`, `Rate of Right Ascen(r/s)`, `SQRT(A)  (m 1/2)`, `Right Ascen at Week(rad)`, `Argument of Perigee(rad)`, `Mean Anom(rad)`, `Af0(s)`, `Af1(s/s)`, `week`. The exact source key for square-root semi-major-axis contains two spaces between `A)` and `(m`; the parser intentionally validates that literal live contract and fails closed on schema drift.

The BeiDou constellation page exposes the detailed table with columns `Тип орбиты`, `PRN`, `НОРАД`, `Тип КА`, `Тип системы`, `Дата запуска`, `Факт. сущ. (дней)`, `Примечание`.

## Fail-closed and offline behavior

The online path never accepts an arbitrary URL. A network error, HTTP error, timeout, invalid JSON, missing required field or table-parse error is terminal and reported to the operator; it is never replaced silently by cached, synthetic or legacy data.

Both paths normalize the selected source into canonical TSV and retain SHA-256 provenance. Offline import accepts the same displayed/canonical table content from TXT/TSV/semicolon-delimited files, so disconnected Windows operation does not depend on the IAC site.

This intake layer remains deliberately source-preserving: IAC values are not silently converted into `ScenarioConfig` orbital authority. Dataset-specific GLONASS/GPS/BeiDou orbital mapping, including locale and unit conversion, must be explicit and tested before runnable scenario promotion is enabled.
