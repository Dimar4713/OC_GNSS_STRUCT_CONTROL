# Gravity authority evidence — 2026-08-17

## Failure that exposed the ambiguity

A clean Python CLI -> HTTP -> Orekit DSST E2E request failed closed because the standalone sidecar loaded a gravity provider whose `mu` differed from the scenario value by approximately `8.176e-8` relative. The same code/data revision inside the integration-test JVM had previously selected a provider with `mu = 3.986004415e14`, compatible with the configured `3.986004418e14` at roughly `7.5e-10` relative.

The strict `mu` gate therefore revealed an authority-selection ambiguity; it was not relaxed.

## Root cause class

The reviewed Orekit auxiliary-data directory contains multiple potential-coefficient sources/readers. Relying on lazy automatic gravity reader selection allows process/load history to influence which gravity family becomes authoritative.

## Corrective decision

- high-fidelity scenarios declare `gravity_model: EIGEN-6S`;
- the value participates in the normalized force-model SHA-256;
- the Java runtime clears automatic potential-coefficient readers and installs only the ICGEM reader matching `^eigen-6s-truncated$`;
- Java rejects a request whose declared model does not equal the runtime authority;
- Python rejects a result whose metadata authority does not equal the request;
- health/result/run evidence carries `gravity_model` separately from `orekit_data_revision` and `orekit_data_sha256`;
- the configured/provider `mu` compatibility threshold stays strict.

## Acceptance evidence required on the final SHA

1. Ruff green.
2. mypy green.
3. pytest green, including explicit gravity-authority and ROE finite-difference tests.
4. Fresh Java runtime resolves EIGEN-6S deterministically.
5. Java DSST and numerical integration suite green on the reviewed Orekit-data revision.
6. 8x8 + Moon/Sun/SRP direct Java smoke green.
7. `/healthz` reports EIGEN-6S and reviewed data revision/content SHA.
8. Python CLI -> HTTP -> DSST design -> Parquet/JSON/report artifacts green.
9. Python CLI -> HTTP -> numerical validation -> Parquet/JSON/report artifacts green.
10. Real HTTP Orekit finite-difference `A/B/d` smoke green, including positive tangential `delta-a` response.

No operational GNSS constellation parameters are introduced by this evidence scenario.
