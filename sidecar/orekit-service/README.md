# Orekit authoritative sidecar

This service is the high-fidelity ballistic authority for `constellation-control`.
It deliberately accepts only `design` and `validation` propagation requests.
There is no synthetic fallback.

## Runtime identity

- Java 17+
- Orekit 13.1.7
- local `orekit-data` directory supplied through `OREKIT_DATA_PATH`
- SHA-256 of the complete data directory is returned as `orekit_data_sha256`
- propagation requests carry the exact Python-side `force_model_fingerprint`

For CI the official Orekit data repository is pinned to:

```text
f395924f27b6074c8db1432350f5917d722ff3e1
```

Production deployments should pin an explicitly reviewed data revision suitable
for the scenario epoch. Updating auxiliary data is a controlled model change,
not a transparent maintenance action. CI also logs the current official `main`
revision so drift from the reviewed pin is visible without changing the run's
physical-data authority.

## Build and test

```bash
export OREKIT_DATA_PATH=/absolute/path/to/orekit-data
mvn -B test
mvn -B package
```

The integration suite executes:

- DSST design propagation;
- numerical validation propagation;
- force-model-consistent mean -> osculating -> mean round-trip;
- zonal and tesseral gravity paths;
- Moon/Sun/SRP paths;
- RTN/QSW impulsive manoeuvres, including an impulse exactly at the epoch;
- fail-closed checks for force combinations that cannot yet preserve the mean-element invariant.

## Run

```bash
export OREKIT_DATA_PATH=/absolute/path/to/orekit-data
export OREKIT_PORT=8081
java -jar target/orekit-service-0.1.0-SNAPSHOT.jar
```

Health endpoint:

```bash
curl http://127.0.0.1:8081/healthz
```

Authoritative propagation endpoint:

```text
POST /v1/propagate
```

## Container

Build with this directory as Docker context:

```bash
docker build -t constellation-control-orekit:13.1.7 .
```

Run with auxiliary data mounted read-only:

```bash
docker run --rm \
  -p 127.0.0.1:8081:8081 \
  -v /absolute/path/to/orekit-data:/orekit-data:ro \
  constellation-control-orekit:13.1.7
```

The image runs as a non-root user and does not bundle auxiliary data. This keeps
the code image and the physical-data revision independently identifiable.

## Force-model semantics

`reference_radius_m` and `flattening` define the Earth ellipsoid used by the
scenario (for example shadow geometry). The geopotential provider carries its
own gravity reference radius `Ae` and gravitational parameter. The sidecar
records both provider values in result metadata and checks that configured `mu`
is compatible with the loaded gravity field. It does **not** incorrectly require
the gravity reference sphere radius to equal the ellipsoid radius.

Mean elements emitted by both authority modes are DSST-consistent with the same
configured force-model family used for propagation. Instantaneous osculating
semi-major axis is never promoted to a secular-drift criterion.

## Explicit limitations

- tides are currently rejected rather than silently ignored;
- relativity is currently rejected in both authority modes because the numerical
  force can be propagated but the current DSST mean converter cannot represent
  the same relativity force; allowing it would violate the force-model-consistent
  mean-element invariant;
- ICRF is rejected as a barycentric frame for this Earth-centered service;
- ITRF is rejected as a propagation frame; it is used internally as body-fixed
  Earth frame where required;
- operational constellation parameters are never embedded in this service.
