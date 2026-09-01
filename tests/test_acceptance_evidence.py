from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from constellation_control.application.acceptance_evidence import export_completed_run_acceptance_evidence
from constellation_control.application.run_duration import run_scenario_with_duration
from constellation_control.preview.consolidated_release_app import render_preview_page_for_test


def _completed_run(tmp_path: Path) -> tuple[Path, str, str]:
    output_root = tmp_path / "runs"
    result = run_scenario_with_duration(Path("scenarios/mvp_45deg.yaml"), output_root, preset="scenario")
    run_dir = result.run_dir
    return output_root, run_dir.parent.name, run_dir.name


def test_completed_run_exports_immutable_checksummed_acceptance_zip(tmp_path: Path) -> None:
    output_root, scenario_id, run_id = _completed_run(tmp_path)

    exported = export_completed_run_acceptance_evidence(
        output_root,
        scenario_id=scenario_id,
        run_id=run_id,
    )

    zip_path = Path(str(exported["zip_path"]))
    assert zip_path.is_file()
    assert len(str(exported["zip_sha256"])) == 64
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert "acceptance_evidence_manifest.json" in names
        assert "kepler_drift_consistency.json" in names
        assert "kepler_drift_consistency.md" in names
        assert "kepler_drift_consistency.html" in names
        manifest = json.loads(archive.read("acceptance_evidence_manifest.json"))
    assert manifest["schema"] == "oc-gnss-acceptance-evidence-v1"
    assert manifest["scenario_id"] == scenario_id
    assert manifest["run_id"] == run_id
    assert manifest["force_model_fingerprint"]
    assert manifest["files"]["kepler_drift_consistency.json"]["sha256"]

    with pytest.raises(ValueError, match="immutable export"):
        export_completed_run_acceptance_evidence(output_root, scenario_id=scenario_id, run_id=run_id)


def test_export_fails_closed_without_independent_drift_evidence(tmp_path: Path) -> None:
    output_root, scenario_id, run_id = _completed_run(tmp_path)
    (output_root / scenario_id / run_id / "kepler_drift_consistency.json").unlink()

    with pytest.raises(ValueError, match="not acceptance-evidence ready"):
        export_completed_run_acceptance_evidence(output_root, scenario_id=scenario_id, run_id=run_id)


def test_packaged_preview_exposes_acceptance_evidence_export() -> None:
    page = render_preview_page_for_test()
    assert 'id="exportAcceptanceEvidenceButton"' in page
    assert "/api/acceptance-evidence/export" in page
    assert "Download evidence ZIP" in page
    assert "synthetic run is not authoritative acceptance" in page
