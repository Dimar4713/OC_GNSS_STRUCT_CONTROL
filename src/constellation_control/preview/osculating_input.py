from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from constellation_control.adapters.orekit.mean_conversion import (
    OrekitMeanConversionClient,
    OsculatingKeplerianElements,
)
from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, ScenarioLineage
from constellation_control.domain.models import ScenarioConfig


class OsculatingInputRequest(BaseModel):
    source_scenario_name: str
    satellite_id: str
    a_m: float = Field(gt=0.0)
    e: float = Field(ge=0.0, lt=1.0)
    i_deg: float = Field(ge=0.0, le=180.0)
    pa_deg: float
    raan_deg: float
    anomaly_deg: float
    anomaly_type: Literal["mean", "eccentric", "true"] = "true"


class OsculatingCreateRequest(OsculatingInputRequest):
    target_scenario_name: str
    new_scenario_id: str


def _elements(request: OsculatingInputRequest) -> OsculatingKeplerianElements:
    return OsculatingKeplerianElements(
        a_m=request.a_m,
        e=request.e,
        i_rad=math.radians(request.i_deg),
        pa_rad=math.radians(request.pa_deg),
        raan_rad=math.radians(request.raan_deg),
        anomaly_rad=math.radians(request.anomaly_deg),
        anomaly_type=request.anomaly_type,
    )


def _source(root: Path, request: OsculatingInputRequest):
    source = load_scenario(root / request.source_scenario_name)
    satellite = next((item for item in source.constellation.satellites if item.satellite_id == request.satellite_id), None)
    if satellite is None:
        raise ValueError(f"unknown satellite_id: {request.satellite_id}")
    if not source.orekit_sidecar_url:
        raise ValueError("selected scenario has no orekit_sidecar_url; authoritative conversion is unavailable")
    return source, satellite


def preview_osculating_conversion(root: Path, request: OsculatingInputRequest) -> dict[str, object]:
    source, satellite = _source(root, request)
    result = OrekitMeanConversionClient(source.orekit_sidecar_url).convert(
        epoch=source.epoch,
        frame=source.frame,
        time_scale=source.time_scale,
        elements=_elements(request),
        spacecraft=satellite.spacecraft,
        force_model=source.force_model,
    )
    return {
        "valid": True,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "satellite_id": satellite.satellite_id,
        "mean_orbit": result.mean_orbit.model_dump(mode="json"),
        "backend_metadata": result.backend_metadata,
    }


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


def create_osculating_derived_scenario(root: Path, request: OsculatingCreateRequest) -> dict[str, object]:
    source, satellite = _source(root, request)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    target = _target(root, request.target_scenario_name)
    result = OrekitMeanConversionClient(source.orekit_sidecar_url).convert(
        epoch=source.epoch,
        frame=source.frame,
        time_scale=source.time_scale,
        elements=_elements(request),
        spacecraft=satellite.spacecraft,
        force_model=source.force_model,
    )
    satellites = tuple(
        item.model_copy(update={"mean_orbit": result.mean_orbit}) if item.satellite_id == request.satellite_id else item
        for item in source.constellation.satellites
    )
    constellation = source.constellation.model_copy(update={"satellites": satellites})
    prior_twin = source.digital_twin or DigitalTwinConfig()
    digital_twin = prior_twin.model_copy(
        update={
            "lineage": ScenarioLineage(
                parent_scenario_id=source.scenario_id,
                parent_config_hash=source.config_hash(),
                transformation="osculating_import",
                random_seed=None,
            )
        }
    )
    child = ScenarioConfig.model_validate(
        source.model_dump(mode="json")
        | {
            "scenario_id": request.new_scenario_id,
            "constellation": constellation.model_dump(mode="json"),
            "digital_twin": digital_twin.model_dump(mode="json"),
        }
    )
    target.write_text(yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "satellite_id": request.satellite_id,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "backend_metadata": result.backend_metadata,
    }


OSCULATING_CARD = r"""
<div class="card" id="osculatingCard">
  <h3>Оскулирующие элементы / Osculating elements</h3>
  <p class="hint">Вводится состояние выбранного КА. Перед созданием сценария выполняется authoritative Orekit DSST osculating→mean conversion; скрытого fallback нет.</p>
  <div class="grid">
    <label>КА / Satellite <select id="oscSat"></select></label>
    <label>a, m <input id="oscA" type="number" step="1" value="26560000"></label>
    <label>e <input id="oscE" type="number" step="0.000001" value="0.001"></label>
    <label>i, deg <input id="oscI" type="number" step="0.001" value="64.8"></label>
    <label>ω, deg <input id="oscPa" type="number" step="0.001" value="0"></label>
    <label>Ω, deg <input id="oscRaan" type="number" step="0.001" value="0"></label>
    <label>Anomaly, deg <input id="oscAnomaly" type="number" step="0.001" value="0"></label>
    <label>Тип / Type <select id="oscType"><option value="true">true</option><option value="mean">mean</option><option value="eccentric">eccentric</option></select></label>
  </div>
  <button onclick="previewOsculating()">Проверить через Orekit / Preview via Orekit</button>
  <pre id="oscPreview"></pre>
  <label>Новый scenario_id <input id="oscScenarioId" type="text" placeholder="derived-osculating-01"></label>
  <label>Новый YAML <input id="oscFile" type="text" placeholder="derived-osculating-01.yaml"></label>
  <button onclick="createOsculating()">Создать производный сценарий / Create derived scenario</button>
  <div id="oscStatus" class="status"></div>
</div>
"""

OSCULATING_SCRIPT = r"""
function oscPayload(){return {source_scenario_name:scenario.value,satellite_id:oscSat.value,a_m:+oscA.value,e:+oscE.value,i_deg:+oscI.value,pa_deg:+oscPa.value,raan_deg:+oscRaan.value,anomaly_deg:+oscAnomaly.value,anomaly_type:oscType.value};}
function syncOsculatingSatellites(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];oscSat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));}
async function previewOsculating(){oscStatus.textContent='Orekit conversion…';const r=await fetch('/api/osculating/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(oscPayload())});const d=await r.json();if(!r.ok){oscStatus.textContent=d.detail||'Conversion failed';oscStatus.className='status danger';return;}oscPreview.textContent=JSON.stringify(d,null,2);oscStatus.textContent='VALID: '+d.backend_metadata.backend+'; '+d.backend_metadata.orekit_version;oscStatus.className='status ok';}
async function createOsculating(){const p={...oscPayload(),new_scenario_id:oscScenarioId.value.trim(),target_scenario_name:oscFile.value.trim()};if(!p.new_scenario_id||!p.target_scenario_name){oscStatus.textContent='Укажите новый scenario_id и YAML';oscStatus.className='status danger';return;}const r=await fetch('/api/osculating/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){oscStatus.textContent=d.detail||'Create failed';oscStatus.className='status danger';return;}const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();oscStatus.textContent='Создан: '+d.scenario_name;oscStatus.className='status ok';}
"""


def install_osculating_routes(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/osculating/preview")
    def preview(request: OsculatingInputRequest) -> dict[str, object]:
        try:
            return preview_osculating_conversion(scenario_root, request)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/osculating/create")
    def create(request: OsculatingCreateRequest) -> dict[str, object]:
        try:
            return create_osculating_derived_scenario(scenario_root, request)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
