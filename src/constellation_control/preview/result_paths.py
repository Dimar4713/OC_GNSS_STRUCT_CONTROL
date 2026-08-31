from __future__ import annotations

from pathlib import Path


def safe_result_file(output_root: Path, scenario_id: str, run_id: str, name: str) -> Path:
    """Resolve one persisted Preview artifact without allowing path traversal."""
    for component in (scenario_id, run_id, name):
        if not component or component in {".", ".."} or Path(component).name != component:
            raise ValueError("Некорректный путь результата / result path contains invalid components")
    root = output_root.resolve()
    candidate = (root / scenario_id / run_id / name).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError("Файл результата не найден / result artifact not found")
    return candidate
