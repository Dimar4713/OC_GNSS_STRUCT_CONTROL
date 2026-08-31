from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from constellation_control.application.run import load_scenario
from constellation_control.domain.spacecraft_catalog import (
    SpacecraftSystemsCatalog,
    validate_operational_systems,
)


class SpacecraftCatalogValidateRequest(BaseModel):
    scenario_name: str
    catalog_text: str


def validate_spacecraft_catalog(scenario_root: Path, request: SpacecraftCatalogValidateRequest) -> dict[str, object]:
    payload = yaml.safe_load(request.catalog_text)
    if not isinstance(payload, dict):
        raise ValueError("spacecraft systems catalog must be a YAML/JSON mapping")
    try:
        catalog = SpacecraftSystemsCatalog.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    scenario = load_scenario(scenario_root / request.scenario_name)
    states = () if scenario.digital_twin is None else scenario.digital_twin.spacecraft_states
    findings = validate_operational_systems(states, catalog)
    valid = all(item.valid for item in findings)
    return {
        "valid": valid,
        "scenario_id": scenario.scenario_id,
        "operational_state_count": len(states),
        "propulsion_catalog_count": len(catalog.propulsion),
        "correction_catalog_count": len(catalog.correction),
        "findings": [item.model_dump(mode="json") for item in findings],
        "calculation_authority": (
            "catalog validation never overwrites scenario mass, fuel, thrust or Isp; "
            "operational state and spacecraft parameters remain numerical authority"
        ),
    }


SPACECRAFT_CATALOG_CARD = r"""
<div class="card" id="spacecraftCatalogCard">
  <h3>Каталог двигателей и систем коррекции / Propulsion & correction catalog</h3>
  <p class="hint">Загрузите YAML/JSON-справочник для проверки model/type/Isp/thrust/propellant/mode. Каталог ничего не подставляет в расчёт: масса, топливо и Isp остаются параметрами выбранного сценария.</p>
  <input id="spacecraftCatalogFile" type="file" accept=".yaml,.yml,.json">
  <button onclick="validateSpacecraftCatalog()">Проверить выбранный сценарий / Validate selected scenario</button>
  <div id="spacecraftCatalogStatus" class="status"></div>
  <pre id="spacecraftCatalogResult"></pre>
</div>
"""

SPACECRAFT_CATALOG_SCRIPT = r"""
async function validateSpacecraftCatalog(){
 const f=document.getElementById('spacecraftCatalogFile').files?.[0];
 if(!f){spacecraftCatalogStatus.textContent='Выберите YAML/JSON каталог';spacecraftCatalogStatus.className='status danger';return;}
 const text=await f.text();
 const r=await fetch('/api/spacecraft-catalog/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_name:scenario.value,catalog_text:text})});
 const d=await r.json();
 if(!r.ok){spacecraftCatalogStatus.textContent=d.detail||'Validation failed';spacecraftCatalogStatus.className='status danger';return;}
 spacecraftCatalogResult.textContent=JSON.stringify(d,null,2);
 spacecraftCatalogStatus.textContent=d.valid?'VALID':'CATALOG MISMATCH';spacecraftCatalogStatus.className=d.valid?'status ok':'status danger';
}
"""


def install_spacecraft_catalog_routes(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/spacecraft-catalog/validate")
    def validate_route(request: SpacecraftCatalogValidateRequest) -> dict[str, object]:
        try:
            return validate_spacecraft_catalog(scenario_root, request)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
