# Completed-run promotion authority

A runnable continuation scenario may be created from a completed run only when the run preserves the full propagation evidence needed to advance the orbital and operational state together.

Required run artifacts are:

- `manifest.json`;
- `scenario.normalized.json`;
- `propagation_result.json`;
- `resources.json`.

Promotion fails closed when any required artifact is absent, when the manifest/config hash does not match the normalized scenario, or when the propagation force-model fingerprint differs from the scenario authority.

The child is built by the propagated-state authority introduced in 0.2.4: its epoch advances by the exact completed horizon, each satellite receives the actual final propagated mean orbit, operational mass and residual propellant advance together, and maneuvers already executed in the parent horizon are removed.

Historical Preview runs that do not contain `propagation_result.json` are intentionally not promotable without rerunning. Reconstructing absolute final mean states from reports, relative diagnostics, ground tracks or resource tables is prohibited.

The remaining integration step is to persist `PropagationResult` atomically into every successful run directory and then expose the promotion core through the packaged operator flow.
