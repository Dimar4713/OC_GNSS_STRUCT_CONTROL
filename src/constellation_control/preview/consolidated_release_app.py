from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ValidationError

from constellation_control.domain.models import ScenarioConfig
from constellation_control.preview.release_app import (
    create_preview_app as create_release_preview_app,
    render_preview_page_for_test as render_release_page,
)

PREVIEW_VERSION = "0.2.3"


class PreviewScenarioDraftRequest(BaseModel):
    yaml_text: str


class PreviewScenarioSaveRequest(PreviewScenarioDraftRequest):
    scenario_name: str


def _validated_scenario_from_yaml(yaml_text: str) -> ScenarioConfig:
    if not yaml_text.strip():
        raise ValueError("YAML пуст / YAML is empty")
    try:
        payload = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML не читается / YAML cannot be parsed: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("ScenarioConfig должен быть YAML mapping / ScenarioConfig must be a YAML mapping")
    try:
        return ScenarioConfig.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def _safe_new_scenario_path(scenario_root: Path, scenario_name: str) -> Path:
    if not scenario_name or Path(scenario_name).name != scenario_name:
        raise ValueError(
            "Имя нового сценария должно быть именем YAML-файла без пути / "
            "new scenario name must be a YAML file name without path components"
        )
    if not scenario_name.lower().endswith((".yaml", ".yml")):
        raise ValueError("Требуется файл .yaml/.yml / scenario name must end with .yaml or .yml")
    root = scenario_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / scenario_name).resolve()
    if candidate.parent != root:
        raise ValueError("Некорректный путь сценария / invalid scenario path")
    if candidate.exists():
        raise ValueError(
            "Файл уже существует; существующие сценарии не перезаписываются / "
            "file already exists; existing scenarios are never overwritten"
        )
    return candidate


def _draft_payload(scenario: ScenarioConfig) -> dict[str, object]:
    return {
        "valid": True,
        "scenario_id": scenario.scenario_id,
        "force_mode": scenario.force_model.mode.value,
        "force_model_fingerprint": scenario.force_model.fingerprint(),
        "duration_s": scenario.duration_s,
        "output_step_s": scenario.output_step_s,
        "normalized": scenario.model_dump(mode="json"),
    }


_EDITOR_CARD = r"""
<div class="card" id="scenarioEditorCard">
  <h3>Редактор сценария / Scenario editor</h3>
  <p class="hint">Редактируется полный ScenarioConfig YAML: эпоха, горизонт и шаг, модель сил, интегратор, ограничения, Monte Carlo, орбитальная группировка, параметры КА и манёвры. Перед сохранением выполняется полная валидация. Существующие YAML не перезаписываются. / Edit the complete ScenarioConfig YAML: epoch, horizon and output step, force model, integrator, constraints, Monte Carlo, constellation, spacecraft and maneuvers. Full validation is required before saving. Existing YAML files are never overwritten.</p>
  <textarea id="scenarioEditor" rows="32" style="width:100%;box-sizing:border-box;font-family:Consolas,monospace"></textarea>
  <button onclick="validateScenarioDraft()">Проверить YAML / Validate YAML</button>
  <input id="scenarioSaveName" value="operator-edited.yaml" style="min-width:260px" aria-label="New scenario file name" />
  <button onclick="saveScenarioDraft()">Сохранить как новый / Save as new</button>
  <pre id="scenarioEditorStatus">Выберите сценарий — полный YAML будет загружен сюда. / Select a scenario to load its complete YAML here.</pre>
</div>
"""

_EDITOR_SCRIPT = r"""
<script>
const scenarioEditorState = { loadedName: null };

async function loadScenarioIntoEditor(name) {
  if (!name) return;
  const response = await fetch('/api/scenarios/' + encodeURIComponent(name));
  const data = await response.json();
  if (!response.ok) {
    document.getElementById('scenarioEditorStatus').textContent = JSON.stringify(data, null, 2);
    return;
  }
  document.getElementById('scenarioEditor').value = data.yaml_text;
  scenarioEditorState.loadedName = name;
  document.getElementById('scenarioEditorStatus').textContent = 'Загружен / Loaded: ' + name;
}

async function validateScenarioDraft() {
  const yamlText = document.getElementById('scenarioEditor').value;
  const response = await fetch('/api/scenario-drafts/validate', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({yaml_text: yamlText})
  });
  const data = await response.json();
  document.getElementById('scenarioEditorStatus').textContent = JSON.stringify(data, null, 2);
}

async function saveScenarioDraft() {
  const yamlText = document.getElementById('scenarioEditor').value;
  const scenarioName = document.getElementById('scenarioSaveName').value;
  const response = await fetch('/api/scenario-drafts/save', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({yaml_text: yamlText, scenario_name: scenarioName})
  });
  const data = await response.json();
  document.getElementById('scenarioEditorStatus').textContent = JSON.stringify(data, null, 2);
  if (response.ok) window.location.reload();
}

document.addEventListener('DOMContentLoaded', () => {
  const select = document.getElementById('scenarioSelect');
  if (!select) return;
  select.addEventListener('change', () => loadScenarioIntoEditor(select.value));
  if (select.value) loadScenarioIntoEditor(select.value);
});
</script>
"""


def _inject_editor(page: str) -> str:
    if "scenarioEditorCard" in page:
        return page
    insertion = _EDITOR_CARD + _EDITOR_SCRIPT
    if "</body>" in page:
        return page.replace("</body>", insertion + "</body>")
    return page + insertion


def render_preview_page_for_test() -> str:
    return _inject_editor(render_release_page()).replace("Engineering Preview 0.2", f"Engineering Preview {PREVIEW_VERSION}")


def create_preview_app(scenario_root: Path, output_root: Path) -> FastAPI:
    scenario_root = Path(scenario_root)
    output_root = Path(output_root)
    base = create_release_preview_app(scenario_root, output_root)
    base.title = f"OC GNSS STRUCT CONTROL Engineering Preview {PREVIEW_VERSION}"
    base.version = PREVIEW_VERSION

    # Replace the root HTML handler while preserving the complete accepted 0.2
    # application/API surface assembled by release_app.
    for route in list(base.router.routes):
        if getattr(route, "path", None) == "/" and "GET" in getattr(route, "methods", set()):
            base.router.routes.remove(route)

    @base.get("/", response_class=HTMLResponse)
    def index() -> str:
        return render_preview_page_for_test()

    @base.get("/api/scenarios/{scenario_name}")
    def scenario_source(scenario_name: str) -> dict[str, object]:
        if Path(scenario_name).name != scenario_name:
            raise HTTPException(status_code=422, detail="invalid scenario name")
        path = scenario_root / scenario_name
        if path.suffix.lower() not in {".yaml", ".yml"} or not path.is_file():
            raise HTTPException(status_code=404, detail="scenario not found")
        return {"name": scenario_name, "yaml_text": path.read_text(encoding="utf-8")}

    @base.post("/api/scenario-drafts/validate")
    def validate_scenario_draft(request: PreviewScenarioDraftRequest) -> dict[str, object]:
        try:
            return _draft_payload(_validated_scenario_from_yaml(request.yaml_text))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @base.post("/api/scenario-drafts/save")
    def save_scenario_draft(request: PreviewScenarioSaveRequest) -> dict[str, object]:
        try:
            scenario = _validated_scenario_from_yaml(request.yaml_text)
            path = _safe_new_scenario_path(scenario_root, request.scenario_name)
            path.write_text(request.yaml_text.rstrip() + "\n", encoding="utf-8", newline="\n")
            return {
                **_draft_payload(scenario),
                "saved": True,
                "name": path.name,
                "message": "Сохранено как новый сценарий / Saved as a new scenario",
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @base.get("/health")
    def health_023() -> dict[str, object]:
        return {
            "status": "ok",
            "preview_version": PREVIEW_VERSION,
            "scenario_editor": "full-yaml-validate-save-as-new",
        }

    return base
