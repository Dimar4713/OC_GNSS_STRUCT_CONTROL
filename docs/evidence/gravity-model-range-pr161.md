# PR #161 — gravity model range acceptance evidence

Accepted engineering increment: explicit Earth-gravity fidelity selection in scenario/UI from Kepler through EIGEN-6S 32x32.

## Functional contract

- `0x0` — Kepler / central-body baseline.
- `2x0` — J2-class zonal model.
- EIGEN-6S degree/order selectable with `0 <= order <= degree <= 32`.
- UI presets: Kepler 0x0, J2 2x0, 4x4, 8x8, 12x12, 16x16, 24x24, 32x32, plus custom degree/order.
- Every accepted gravity-model edit creates a new derived scenario; source YAML is not overwritten.
- Lineage transformation is explicit: `gravity_model_change`.
- Degree/order participate in the force-model fingerprint, so fidelity changes are authority-visible and reproducible.
- Packaged Windows launcher routes through the gravity-enabled Preview wrapper and the packaged UI is checked for the gravity card and 32x32 preset.

## Exact-head acceptance

- PR: #161 — `Verify gravity model range from Kepler to 32x32`.
- Exact accepted head: `0fba2b993385ea0929f5330ccddd657738fe8fcd`.
- `ci` run `33488053043` — GREEN.
- `preview-package-compat` run `33488053088` — GREEN.
- `preview-0.2-package` run `33488053149` — GREEN.
- Real packaged clean-Windows acceptance — GREEN.
- PR merge commit: `9cbbc39a1de07886e9997931a5ad1cf942555450`.

## Accepted Windows artifact

- Name: `engineering-preview-python-0.2.4-win10`.
- Artifact ID: `9792584632`.
- Size: `34,050,281` bytes.
- Digest: `sha256:21481ea9ebfb985441621d1657e5743843eefb3f3e1a94fe635f28fdaa8b43dc`.
- Created: `2026-09-01T08:38:48Z`.
- Expires: `2026-09-15T08:38:46Z`.
- Workflow run: `33488053149`.
- Head SHA embedded by workflow: `0fba2b993385ea0929f5330ccddd657738fe8fcd`.

The earlier artifact `9792363612` was produced by an intermediate run whose Windows smoke failed because the acceptance PowerShell script attempted to assign to the read-only `$HOME` variable. It is not accepted release evidence and must not be advertised.

## Validation use

For adequacy investigations, use the same initial states and horizons under at least `0x0`, `2x0`, `4x4`, `8x8`, `16x16`, and `32x32`, then compare secular phase drift and numerical trajectories. Convergence must be measured rather than assumed.
