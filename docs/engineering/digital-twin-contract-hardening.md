# Digital-twin contract hardening

This note tracks the 0.2.4 hardening slice that follows the explicit Walker/osculating-input cleanup.

Planned invariant: perturbation parameters must be selected from the canonical supported parameter registry, not carried as arbitrary strings. The domain model must reject unsupported parameter names before execution while preserving the existing explicit unit contract and deterministic perturbation semantics.

No propagation authority, force model, integrator, maneuver physics, or mean/osculating conversion authority is changed by this slice.
