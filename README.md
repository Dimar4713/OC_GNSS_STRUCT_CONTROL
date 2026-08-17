# constellation-control

Production-oriented research platform for reproducible analysis, modelling and optimal control of stable orbital constellations.

> **Critical invariant:** an instantaneous osculating semi-major axis is never used as a secular-drift criterion. Drift comparison and design optimisation operate only on mean elements whose definition is bound to the same force-model configuration used by propagation.

## Project tree

```text
src/constellation_control/
  domain/                 # schemas and ports; no Orekit dependency
  application/            # scenario orchestration and run identity
  dynamics/               # screening mechanics and common orbital math
  mean_elements/          # ROE and mean-element transformations
  analysis/               # drift regression and fuel accounting
  optimization/           # LHS, SciPy local optimisation, NSGA-II
  control/                # deadband and impulsive MPC
  uncertainty/            # deterministic Monte Carlo
  reporting/              # JSON/CSV/Parquet/Markdown/HTML + plots
  adapters/synthetic/     # deterministic unit/screening backend
  adapters/orekit/        # authoritative Orekit boundary
  api/                    # optional FastAPI layer
  cli/                    # Typer CLI
scenarios/
tests/
docs/
  adr/
```

## Accuracy modes

- **screening** — two-body + first-order J2 secular rates. Fast candidate search only.
- **design** — authoritative Orekit DSST service. Zonal/tesseral gravity, Sun/Moon, SRP and consistent mean↔osculating mapping.
- **validation** — authoritative Orekit numerical propagation. Full configured gravity, third bodies, SRP/eclipses and manoeuvres.

The current MVP implements the complete screening path and the production boundary to an Orekit sidecar. `design` and `validation` deliberately fail closed when the Orekit service is absent; there is no silent fallback to screening.

## Quickstart

Python 3.12+:

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -e '.[dev]'
pytest -q
constellation-control run scenarios/mvp_45deg.yaml --output runs
```

The example is a **synthetic demonstration scenario**, not a declaration of operational GNSS constellation parameters. All orbital, spacecraft, force-model and constraint values enter through YAML.

Optional API:

```bash
pip install -e '.[api]'
uvicorn constellation_control.api.app:app --reload
```

Optional JPype runtime for direct Orekit experiments:

```bash
pip install -e '.[orekit]'
```

The repository currently pins `orekit-jpype==13.1.5.0`. The Java Orekit project has released 13.1.6, so a 13.1.6 migration is accepted only after wrapper/sidecar compatibility is verified and the force-model/runtime fingerprint changes accordingly.

## Reproducibility contract

Every run records `scenario_id`, deterministic `run_id`, normalized config hash, code version, backend identity/version, force-model fingerprint, epoch, algorithm versions and random seed. Core results are written to JSON + CSV + Parquet; reports are emitted as Markdown + HTML.

## Engineering status

- Mission umbrella: #1
- Architecture/reproducibility: #2
- Screening/drift physics: #3
- Optimisation/control: #4
- Monte Carlo/reporting: #5
- Orekit DSST + numerical validation: #6

See `docs/roadmap.md` and `docs/validation.md` for acceptance gates and known gaps.
