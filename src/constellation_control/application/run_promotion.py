from __future__ import annotations

import json
from pathlib import Path

from constellation_control.application.propagated_child import save_propagated_child
from constellation_control.domain.models import ExperimentRunManifest, PropagationResult, ScenarioConfig

_REQUIRED_RUN_FILES = {
    "manifest.json",
    "scenario.normalized.json",
    "propagation_result.json",
    "resources.json",
}


def _safe_run_dir(output_root: Path, scenario_id: str, run_id: str) -> Path:
    if not scenario_id or Path(scenario_id).name != scenario_id:
        raise ValueError("invalid scenario_id")
    if not run_id or Path(run_id).name != run_id:
        raise ValueError("invalid run_id")
    root = output_root.resolve()
    run_dir = (root / scenario_id / run_id).resolve()
    if run_dir.parent != (root / scenario_id).resolve():
        raise ValueError("invalid run path")
    if not run_dir.is_dir():
        raise ValueError("run directory does not exist")
    return run_dir


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read run artifact {path.name}: {exc}") from exc


def load_promotable_run(
    output_root: Path,
    *,
    scenario_id: str,
    run_id: str,
) -> tuple[ScenarioConfig, PropagationResult, ExperimentRunManifest]:
    run_dir = _safe_run_dir(output_root, scenario_id, run_id)
    missing = sorted(name for name in _REQUIRED_RUN_FILES if not (run_dir / name).is_file())
    if missing:
        raise ValueError(f"run is not promotable; missing artifacts: {missing}")

    manifest = ExperimentRunManifest.model_validate(_load_json(run_dir / "manifest.json"))
    source = ScenarioConfig.model_validate(_load_json(run_dir / "scenario.normalized.json"))
    result = PropagationResult.model_validate(_load_json(run_dir / "propagation_result.json"))

    if manifest.scenario_id != scenario_id or source.scenario_id != scenario_id:
        raise ValueError("run scenario identity does not match requested scenario_id")
    if manifest.run_id != run_id:
        raise ValueError("manifest run_id does not match requested run_id")
    if manifest.config_hash != source.config_hash():
        raise ValueError("manifest config hash does not match normalized scenario")
    force_fingerprint = source.force_model.fingerprint()
    if manifest.force_model_fingerprint != force_fingerprint:
        raise ValueError("manifest force-model fingerprint does not match normalized scenario")
    if result.force_model_fingerprint != force_fingerprint:
        raise ValueError("propagation result force-model fingerprint does not match normalized scenario")

    resources = _load_json(run_dir / "resources.json")
    if not isinstance(resources, list):
        raise ValueError("resources.json must contain a JSON array")
    return source, result, manifest


def list_promotable_runs(output_root: Path) -> list[dict[str, str]]:
    root = output_root.resolve()
    if not root.exists():
        return []
    items: list[dict[str, str]] = []
    for scenario_dir in sorted(path for path in root.iterdir() if path.is_dir() and path.name != "state-snapshots"):
        for run_dir in sorted(path for path in scenario_dir.iterdir() if path.is_dir()):
            if not all((run_dir / name).is_file() for name in _REQUIRED_RUN_FILES):
                continue
            try:
                source, _, manifest = load_promotable_run(
                    root,
                    scenario_id=scenario_dir.name,
                    run_id=run_dir.name,
                )
            except ValueError:
                continue
            items.append(
                {
                    "scenario_id": source.scenario_id,
                    "run_id": manifest.run_id,
                    "backend": manifest.backend,
                    "epoch": source.epoch.isoformat(),
                }
            )
    return items


def promote_completed_run(
    scenario_root: Path,
    output_root: Path,
    *,
    scenario_id: str,
    run_id: str,
    target_scenario_name: str,
    new_scenario_id: str,
) -> dict[str, object]:
    source, result, manifest = load_promotable_run(
        output_root,
        scenario_id=scenario_id,
        run_id=run_id,
    )
    saved = save_propagated_child(
        scenario_root,
        source,
        result,
        target_scenario_name=target_scenario_name,
        new_scenario_id=new_scenario_id,
    )
    return {
        **saved,
        "source_run_id": manifest.run_id,
        "source_backend": manifest.backend,
        "source_backend_version": manifest.backend_version,
    }
