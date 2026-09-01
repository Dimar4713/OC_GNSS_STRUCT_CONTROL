from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from constellation_control.application.run_promotion import load_promotable_run

_REQUIRED_ACCEPTANCE_FILES = (
    "manifest.json",
    "scenario.normalized.json",
    "propagation_result.json",
    "resources.json",
    "summary.json",
    "timeseries.csv",
    "kepler_drift_consistency.json",
    "kepler_drift_consistency.md",
    "kepler_drift_consistency.html",
)
_OPTIONAL_ACCEPTANCE_FILES = (
    "report.md",
    "report.html",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError(f"invalid {label}")
    return value


def export_completed_run_acceptance_evidence(
    output_root: Path,
    *,
    scenario_id: str,
    run_id: str,
) -> dict[str, object]:
    """Export immutable, checksummed acceptance evidence from a completed run.

    The exporter never reruns propagation or reconstructs missing data. It fails closed
    unless the completed run contains the full propagation authority plus the independent
    Kepler drift consistency artifacts required for physical acceptance.
    """

    scenario_id = _safe_component(scenario_id, "scenario_id")
    run_id = _safe_component(run_id, "run_id")
    source, _, manifest = load_promotable_run(output_root, scenario_id=scenario_id, run_id=run_id)
    run_dir = output_root.resolve() / scenario_id / run_id

    missing = [name for name in _REQUIRED_ACCEPTANCE_FILES if not (run_dir / name).is_file()]
    if missing:
        raise ValueError(f"run is not acceptance-evidence ready; missing artifacts: {missing}")

    export_root = output_root.resolve() / "acceptance-evidence"
    export_root.mkdir(parents=True, exist_ok=True)
    package_id = f"{scenario_id}--{run_id}"
    package_dir = export_root / package_id
    zip_path = export_root / f"{package_id}.zip"
    if package_dir.exists() or zip_path.exists():
        raise ValueError("acceptance evidence package already exists; immutable export will not overwrite it")
    package_dir.mkdir()

    names = list(_REQUIRED_ACCEPTANCE_FILES)
    names.extend(name for name in _OPTIONAL_ACCEPTANCE_FILES if (run_dir / name).is_file())
    files: dict[str, dict[str, object]] = {}
    for name in names:
        source_path = run_dir / name
        target = package_dir / name
        shutil.copyfile(source_path, target)
        files[name] = {"sha256": _sha256(target), "size_bytes": target.stat().st_size}

    evidence_manifest = {
        "schema": "oc-gnss-acceptance-evidence-v1",
        "package_id": package_id,
        "scenario_id": scenario_id,
        "run_id": run_id,
        "backend": manifest.backend,
        "backend_version": manifest.backend_version,
        "force_mode": source.force_model.mode.value,
        "force_model_fingerprint": source.force_model.fingerprint(),
        "gravity_degree": source.force_model.gravity_degree,
        "gravity_order": source.force_model.gravity_order,
        "integrator": source.integrator.model_dump(mode="json"),
        "epoch": source.epoch.isoformat(),
        "duration_s": source.duration_s,
        "output_step_s": source.output_step_s,
        "files": files,
        "authority_note": (
            "Exported from persisted completed-run evidence only; no propagation rerun, "
            "metric reconstruction, or input tuning was performed."
        ),
    }
    manifest_path = package_dir / "acceptance_evidence_manifest.json"
    manifest_path.write_text(json.dumps(evidence_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.iterdir()):
            archive.write(path, arcname=path.name)

    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "zip_path": str(zip_path),
        "zip_name": zip_path.name,
        "zip_sha256": _sha256(zip_path),
        "manifest": evidence_manifest,
    }
