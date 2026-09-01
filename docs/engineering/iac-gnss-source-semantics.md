# IAC GNSS source semantics

The glonass-iac.ru integration preserves the source-declared meaning and units of every imported field before any later conversion to project orbital authority.

## GPS

Source page: `https://glonass-iac.ru/gps/ephemeris/`.

- `PRN` — GPS pseudorandom-noise sequence/satellite number.
- `Date` — base date in UTC, `DD.MM.YY`.
- `t` — seconds from the base date.
- `e` — eccentricity.
- `i` — inclination, degrees.
- `dΩ/dt` — rate of right ascension of the ascending node, degrees per second.
- `A` — semi-major axis, kilometres.
- `LΩ` — longitude/right ascension of the ascending node at 00:00:00 of the base date, degrees.
- `ω` — argument of perigee, degrees.
- `m` — mean anomaly, degrees.
- `af0` — satellite-clock correction, seconds.
- `af1` — rate of change of `af0`, seconds per second.

The IAC JSON currently uses decimal-comma strings. Locale conversion is explicit; values are not silently reinterpreted.

## BeiDou

Source page: `https://glonass-iac.ru/beidou/ephemeris/`.

- `PRN` — satellite number.
- `H` — health indicator; `000` means healthy.
- `e` — eccentricity.
- `t` — time from the source base epoch, seconds.
- `δi` — orbital inclination, radians, per source declaration.
- `Ω` — right-ascension rate, radians per second.
- `A` — source field presented by the live JSON as `SQRT(A)  (m 1/2)`; the raw square-root value is retained verbatim and its square is exposed explicitly. The source-page wording `квадратный корень большой полуоси [полуциклы]` is preserved as documentation evidence but is not used to reinterpret the live numeric field as an angular unit.
- `Ω0` — ascending-node longitude/right ascension at the weekly epoch, radians.
- `ω` — argument of perigee, radians.
- `m` — mean anomaly, radians.
- `af0` — satellite-clock correction, seconds.
- `af1` — rate of change of `af0`, seconds per second.
- `week` — source week counter exposed by the live JSON.

Source attribution states that BeiDou data are provided from the Test and Evaluation Research Center under the China Satellite Navigation Office.

## Galileo

The IAC KVNO pages reviewed for this integration do **not** provide a Galileo almanac source. Galileo must therefore remain explicitly unavailable for the `glonass-iac` provider. The application must not silently substitute another provider or synthetic data under the IAC source identity. A separate Galileo provider/adapter may be added later with its own provenance and authority contract.
