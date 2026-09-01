# IAC GNSS online/offline intake

Engineering Preview accepts GNSS source tables from the Information and Analysis Center (`glonass-iac.ru`) in two equivalent intake modes:

- online fetch from a fixed allowlist of four project-reviewed URLs;
- offline import of a saved TXT/TSV/semicolon-delimited table for the same dataset.

Supported datasets:

- GLONASS almanac — `https://glonass-iac.ru/glonass/ephemeris/`;
- GPS almanac — `https://glonass-iac.ru/gps/ephemeris/`;
- BeiDou almanac — `https://glonass-iac.ru/beidou/ephemeris/`;
- BeiDou constellation composition — `https://glonass-iac.ru/beidou/sostavOG/`.

The online path never accepts an arbitrary URL. A network error, HTTP error, timeout or table-parse error is terminal and reported to the operator; it is never replaced silently by cached, synthetic or legacy data.

Both paths normalize the selected table into canonical TSV and retain SHA-256 provenance. This first intake layer is deliberately source-preserving: unknown IAC columns are not silently mapped into `ScenarioConfig` orbital authority. Dataset-specific GLONASS/GPS/BeiDou orbital mapping must be implemented explicitly and verified against saved IAC examples before runnable scenario promotion is enabled.

This separation keeps offline operation fully available while preventing loss of source lineage or accidental promotion of a changed web-table schema.
