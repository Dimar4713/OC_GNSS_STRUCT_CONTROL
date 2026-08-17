# Validation and acceptance

## Implemented automated evidence
- two-body/J2=0 mean-motion check against analytic Kepler mean motion;
- identical mean orbits with phase offset preserve zero relative secular drift in J2 screening;
- harmonic regression recovers a known injected secular slope;
- positive tangential impulse increases orbital energy/semi-major axis and therefore reduces mean motion;
- deadband controller rejects a candidate violating hard minimum distance;
- Tsiolkovsky propellant calculation property test;
- deterministic Monte Carlo with fixed seed under parallel execution;
- end-to-end YAML -> propagation -> metrics -> JSON/CSV/Parquet/Markdown/HTML artifact test.

## Required next fidelity gates
1. Independent numerical estimate of first-order J2 `Omega_dot`, `omega_dot`, `M_dot` over a declared validity envelope.
2. Orekit mean->osc->mean round trip tolerance test.
3. Symmetry test on a multi-spacecraft symmetric scenario.
4. Full controller post-propagation safety validation under Orekit.
5. Top-K design replay in numerical validation.
6. Monte Carlo uncertainty sources expanded to injection, OD, manoeuvre magnitude/direction/time, `Cr*A/m` and window availability.

No item in this section may be represented as complete merely because the screening backend passes.
