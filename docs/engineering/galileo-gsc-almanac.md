# Galileo GSC almanac online/offline intake

The project uses the European GNSS Service Centre (GSC) as the reviewed Galileo almanac source.

Public product index:

- `https://www.gsc-europa.eu/gsc-products/almanac`

The GSC page publishes the current XML and historical XML records. The current public product observed on 2026-09-02 is `2026-08-28.xml`. GSC also documents the newer daily `GalileoGSCAlmanac_<yyyymmddhhmmss>_<free-text>.xml` naming convention. Discovery accepts only HTTPS links on `www.gsc-europa.eu` below `/sites/default/files/sites/all/files/` and only these reviewed filename families.

## Source-declared semantics

Per the GSC product description / Galileo OS SIS ICD:

- `SVID` — Galileo satellite ID;
- `aSqRoot` — difference from the square root of the nominal semi-major axis of 29 600 km, in m^1/2; it is **not** the complete sqrt(A);
- `ecc` — eccentricity;
- `deltai` — inclination difference relative to 56 degrees, in semicircles;
- `omega0` — right ascension in semicircles;
- `omegaDot` — right-ascension rate in semicircles/s;
- `w` — argument of perigee in semicircles;
- `m0` — mean anomaly at reference time in semicircles;
- `af0` — clock bias, s;
- `af1` — clock linear term, s/s;
- `iod` — almanac issue of data;
- `t0a` — almanac reference time, s;
- `wna` — modulo-4 representation of Galileo System Time week number; the importer deliberately does not silently expand it to a full week;
- `statusE5a`, `statusE5b`, `statusE1B` — source signal-health status.

One semicircle is converted explicitly as `pi` radians. Derived full values are exposed as properties:

- `sqrt_a = sqrt(29_600_000 m) + aSqRoot`;
- `a = sqrt_a^2`;
- `i = 56 deg + deltai*pi`;
- other angular values multiply the source semicircle value by `pi`.

## Intake modes and authority

Online mode first reads the fixed GSC product index, discovers the latest allowlisted XML link, then downloads and parses that XML. Network failure, index schema drift, unsupported link, invalid XML, missing required field, invalid range or duplicate SVID is terminal and fail-closed.

Offline mode accepts a saved `.xml` file and executes the same semantic parser without network access. Both modes retain the source filename and SHA-256 provenance.

This layer is source-normalization only. It does not silently promote Galileo almanac values into project `MeanOrbit` / runnable `ScenarioConfig` authority. Full Galileo week resolution and reviewed almanac-to-state promotion remain explicit follow-up steps.

A live probe from the AIMETON main server on 2026-09-02 reached a connection refusal from the GSC route, while the public GSC page and current XML link remained externally visible. Therefore the application must keep the offline XML path operational and report online network failures directly rather than falling back silently.
