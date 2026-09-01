from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class GravityModelCreateRequest(BaseModel):
    source_scenario_name: str
    target_scenario_name: str
    new_scenario_id: str
    gravity_degree: int = Field(ge=0, le=32)
    gravity_order: int = Field(ge=0, le=32)

    @model_validator(mode="after")
    def validate_degree_order(self) -> "GravityModelCreateRequest":
        if self.gravity_order > self.gravity_degree:
            raise ValueError("gravity_order must not exceed gravity_degree")
        if self.gravity_degree == 0 and self.gravity_order != 0:
            raise ValueError("Kepler mode requires degree=0 and order=0")
        return self


def _target(root: Path, name: str) -> Path:
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise ValueError("target_scenario_name must be a new YAML file name without path components")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / name).resolve()
    if target.parent != root:
        raise ValueError("invalid target scenario path")
    if target.exists():
        raise ValueError("target scenario already exists; overwrite is forbidden")
    return target


def gravity_model_label(degree: int, order: int) -> str:
    if degree == 0 and order == 0:
        return "KEPLER"
    if degree == 2 and order == 0:
        return "J2 / EIGEN-6S 2x0"
    return f"EIGEN-6S {degree}x{order}"


def create_gravity_derived_scenario(root: Path, request: GravityModelCreateRequest) -> dict[str, object]:
    source = load_scenario(root / request.source_scenario_name)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _target(root, request.target_scenario_name)

    force_model = source.force_model.model_copy(
        update={"gravity_degree": request.gravity_degree, "gravity_order": request.gravity_order}
    )
    prior_twin = source.digital_twin or DigitalTwinConfig()
    digital_twin = prior_twin.model_copy(
        update={
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="gravity_model_change",
                random_seed=None,
            )
        }
    )
    child = ScenarioConfig.model_validate(
        source.model_dump(mode="json")
        | {
            "scenario_id": request.new_scenario_id,
            "force_model": force_model.model_dump(mode="json"),
            "digital_twin": digital_twin.model_dump(mode="json"),
        }
    )
    target.write_text(yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "parent_scenario_id": source.scenario_id,
        "gravity_degree": request.gravity_degree,
        "gravity_order": request.gravity_order,
        "gravity_label": gravity_model_label(request.gravity_degree, request.gravity_order),
        "force_model_fingerprint": child.force_model.fingerprint(),
        "child_config_hash": child.config_hash(),
    }


GRAVITY_MODEL_CARD = r"""
<div class="card" id="gravityModelCard">
  <h3>Модель ГПЗ / Earth gravity model</h3>
  <p class="hint">Явный выбор сложности гравитационного поля для производного сценария. Kepler = 0x0; J2 = 2x0; полная EIGEN-6S допускает degree/order до 32x32. Order не может превышать degree.</p>
  <div class="grid">
    <label>Preset
      <select id="gravityPreset" onchange="applyGravityPreset()">
        <option value="kepler">Kepler 0x0</option>
        <option value="j2">J2 / 2x0</option>
        <option value="4">EIGEN-6S 4x4</option>
        <option value="8" selected>EIGEN-6S 8x8</option>
        <option value="12">EIGEN-6S 12x12</option>
        <option value="16">EIGEN-6S 16x16</option>
        <option value="24">EIGEN-6S 24x24</option>
        <option value="32">EIGEN-6S 32x32</option>
        <option value="custom">Custom</option>
      </select>
    </label>
    <label>Degree n <input id="gravityDegree" type="number" min="0" max="32" step="1" value="8"></label>
    <label>Order m <input id="gravityOrder" type="number" min="0" max="32" step="1" value="8"></label>
  </div>
  <div id="gravityCurrent" class="status"></div>
  <label>Новый scenario_id <input id="gravityScenarioId" type="text" placeholder="derived-gravity-32x32"></label>
  <label>Новый YAML <input id="gravityScenarioFile" type="text" placeholder="derived-gravity-32x32.yaml"></label>
  <button onclick="createGravityScenario()">Создать сценарий с выбранной моделью ГПЗ / Create scenario</button>
  <div id="gravityStatus" class="status"></div>
</div>
"""

GRAVITY_MODEL_SCRIPT = r"""
function applyGravityPreset(){const v=gravityPreset.value;if(v==='kepler'){gravityDegree.value=0;gravityOrder.value=0;}else if(v==='j2'){gravityDegree.value=2;gravityOrder.value=0;}else if(v!=='custom'){gravityDegree.value=Number(v);gravityOrder.value=Number(v);}}
function syncGravityModel(){if(!current)return;const f=(current.normalized||current).force_model||{};gravityDegree.value=f.gravity_degree;gravityOrder.value=f.gravity_order;gravityCurrent.textContent='Current: EIGEN-6S '+f.gravity_degree+'x'+f.gravity_order+'; fingerprint='+((current.force_model_fingerprint)||'');}
async function createGravityScenario(){const n=Number(gravityDegree.value),m=Number(gravityOrder.value);if(!Number.isInteger(n)||!Number.isInteger(m)||n<0||m<0||n>32||m>32||m>n){gravityStatus.textContent='Требуется 0 <= order <= degree <= 32';gravityStatus.className='status danger';return;}const p={source_scenario_name:scenario.value,target_scenario_name:gravityScenarioFile.value.trim(),new_scenario_id:gravityScenarioId.value.trim(),gravity_degree:n,gravity_order:m};if(!p.target_scenario_name||!p.new_scenario_id){gravityStatus.textContent='Укажите новый scenario_id и YAML';gravityStatus.className='status danger';return;}gravityStatus.textContent='Создание…';const r=await fetch('/api/gravity-model/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){gravityStatus.textContent=d.detail||'Create failed';gravityStatus.className='status danger';return;}const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();gravityStatus.textContent='Создан: '+d.scenario_name+'; '+d.gravity_label;gravityStatus.className='status ok';}
"""


def install_gravity_model_routes(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/gravity-model/create")
    def create(request: GravityModelCreateRequest) -> dict[str, object]:
        try:
            return create_gravity_derived_scenario(scenario_root, request)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
