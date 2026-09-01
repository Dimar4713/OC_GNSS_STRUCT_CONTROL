# Galileo GSC source evidence

Verified from the official European GNSS Service Centre product page on 2026-09-02:

- product index: `https://www.gsc-europa.eu/gsc-products/almanac`;
- current listed Almanac XML date: `2026-08-28`;
- `aSqRoot` is the difference from the square root of nominal semi-major axis `29 600 km`, units `m^1/2`;
- `deltai`, `omega0`, `omegaDot`, `w`, `m0` use semicircle-based units;
- `1 semicircle = pi rad`;
- `wna` is Galileo System Time week number modulo 4;
- signal health fields are `statusE5a`, `statusE5b`, `statusE1B`.

The AIMETON main-server probe to GSC encountered a connection refusal on 2026-09-02. That network event is treated as transport evidence only; it does not alter the official source contract. Online intake remains fail-closed and the offline XML path remains required.
