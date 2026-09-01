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

## Canonical acceptance-evidence export

A completed run can also be exported for independent engineering acceptance without creating a continuation scenario. The Preview operator flow provides an **Export evidence ZIP** action for this purpose.

The acceptance export is intentionally stricter than ordinary continuation promotion. In addition to the authoritative propagation files above, it requires:

- `summary.json`;
- `timeseries.csv`;
- `kepler_drift_consistency.json`;
- `kepler_drift_consistency.md`;
- `kepler_drift_consistency.html`.

`report.md` and `report.html` are included when present.

The exporter:

1. validates the completed-run scenario identity, config hash and force-model fingerprint through the existing promotion authority;
2. copies persisted artifacts only — it never reruns propagation, reconstructs missing values or tunes input parameters;
3. records SHA-256 and byte size for every included artifact in `acceptance_evidence_manifest.json`;
4. records backend/version, force mode and fingerprint, gravity degree/order, integrator, epoch, duration and output step;
5. creates an immutable ZIP under `results/acceptance-evidence/`; an existing package is never overwritten.

This export is the intended hand-off for the GLONASS small-drift acceptance case tracked by issue #171. A synthetic run may verify the exporter mechanics, but it does **not** replace the required real/source-derived GLONASS authoritative run.

The operator can download the ZIP directly from Preview and attach or otherwise archive it as canonical evidence. The ZIP SHA-256 shown in the UI identifies the exact package used for review.
