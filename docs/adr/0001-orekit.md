# ADR-0001: Orekit is the authoritative high-fidelity backend

Status: accepted.

Decision: use Orekit for design/validation physics. Domain logic depends only on a `Propagator` port. Screening remains in Python for speed/tests. High-fidelity execution may use JPype or a Java sidecar, but results must identify Orekit and match the requested force-model fingerprint.

Rationale: avoid maintaining a bespoke production geopotential integrator and gain established force models, frames, time scales, DSST and numerical propagation.

Consequence: no silent fallback to screening. Orekit data/runtime versions are reproducibility inputs.
