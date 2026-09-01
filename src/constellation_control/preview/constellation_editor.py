from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import DigitalTwinConfig, PerturbationScope, ScenarioLineage
from constellation_control.domain.models import ConstellationSpec, PlaneSpec, SatelliteSpec, ScenarioConfig, SpacecraftModel


class ConstellationEditRequest(BaseModel):
    source_scenario_name: str
    operation: Literal["rename", "remove", "move", "edit", "clone"]
    satellite_id: str
    new_satellite_id: str | None = None
    plane_id: str | None = None
    role: Literal["reference", "additional"] | None = None
    reference_id: str | None = None
    spacecraft: SpacecraftModel | None = None
    target_scenario_name: str
    new_scenario_id: str


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


def _rename_tuple(values: tuple[str, ...], old: str, new: str) -> tuple[str, ...]:
    return tuple(new if value == old else value for value in values)


def _rebuild_planes(satellites: tuple[SatelliteSpec, ...], existing: tuple[PlaneSpec, ...]) -> tuple[PlaneSpec, ...]:
    ordered = [plane.plane_id for plane in existing]
    for sat in satellites:
        if sat.plane_id not in ordered:
            ordered.append(sat.plane_id)
    return tuple(
        PlaneSpec(plane_id=plane_id, satellite_ids=tuple(s.satellite_id for s in satellites if s.plane_id == plane_id))
        for plane_id in ordered
        if any(s.plane_id == plane_id for s in satellites)
    )


def _with_lineage(source: ScenarioConfig, constellation: ConstellationSpec, digital_twin: DigitalTwinConfig | None, scenario_id: str) -> ScenarioConfig:
    twin = digital_twin or DigitalTwinConfig()
    twin = twin.model_copy(update={
        "lineage": ScenarioLineage(
            parent_scenario_id=source.scenario_id,
            parent_config_hash=source.config_hash(),
            transformation="constellation_editor",
            random_seed=None,
        )
    })
    return ScenarioConfig.model_validate(source.model_dump(mode="json") | {
        "scenario_id": scenario_id,
        "constellation": constellation.model_dump(mode="json"),
        "digital_twin": twin.model_dump(mode="json"),
    })


def _rename(source: ScenarioConfig, old: str, new: str) -> ScenarioConfig:
    new = new.strip()
    if not new:
        raise ValueError("new satellite_id must not be empty")
    ids = {sat.satellite_id for sat in source.constellation.satellites}
    if old not in ids:
        raise ValueError(f"unknown satellite_id: {old}")
    if new != old and new in ids:
        raise ValueError(f"satellite_id already exists: {new}")

    satellites = tuple(
        sat.model_copy(update={
            "satellite_id": new if sat.satellite_id == old else sat.satellite_id,
            "reference_id": new if sat.reference_id == old else sat.reference_id,
        })
        for sat in source.constellation.satellites
    )
    planes = _rebuild_planes(satellites, source.constellation.planes)
    constellation = ConstellationSpec(satellites=satellites, planes=planes)

    maneuvers = tuple(
        maneuver.model_copy(update={"satellite_id": new if maneuver.satellite_id == old else maneuver.satellite_id})
        for maneuver in source.maneuvers
    )
    twin = source.digital_twin
    if twin is not None:
        states = tuple(state.model_copy(update={"satellite_id": new if state.satellite_id == old else state.satellite_id}) for state in twin.spacecraft_states)
        groups = tuple(group.model_copy(update={"satellite_ids": _rename_tuple(group.satellite_ids, old, new)}) for group in twin.groups)
        rules = tuple(
            rule.model_copy(update={"target_ids": _rename_tuple(rule.target_ids, old, new)})
            if rule.scope == PerturbationScope.SATELLITE else rule
            for rule in twin.perturbations
        )
        applied = tuple(item.model_copy(update={"satellite_id": new if item.satellite_id == old else item.satellite_id}) for item in twin.applied_perturbations)
        twin = twin.model_copy(update={"spacecraft_states": states, "groups": groups, "perturbations": rules, "applied_perturbations": applied})

    return ScenarioConfig.model_validate(source.model_dump(mode="json") | {
        "constellation": constellation.model_dump(mode="json"),
        "maneuvers": [item.model_dump(mode="json") for item in maneuvers],
        "digital_twin": twin.model_dump(mode="json") if twin is not None else None,
    })


def _remove(source: ScenarioConfig, satellite_id: str) -> ScenarioConfig:
    sat = next((item for item in source.constellation.satellites if item.satellite_id == satellite_id), None)
    if sat is None:
        raise ValueError(f"unknown satellite_id: {satellite_id}")
    dependencies: list[str] = []
    if any(item.reference_id == satellite_id for item in source.constellation.satellites):
        dependencies.append("reference_id")
    if any(item.satellite_id == satellite_id for item in source.maneuvers):
        dependencies.append("maneuvers")
    twin = source.digital_twin
    if twin is not None:
        if any(state.satellite_id == satellite_id for state in twin.spacecraft_states):
            dependencies.append("digital_twin.spacecraft_states")
        if any(satellite_id in group.satellite_ids for group in twin.groups):
            dependencies.append("digital_twin.groups")
        if any(rule.scope == PerturbationScope.SATELLITE and satellite_id in rule.target_ids for rule in twin.perturbations):
            dependencies.append("digital_twin.perturbations")
        if any(item.satellite_id == satellite_id for item in twin.applied_perturbations):
            dependencies.append("digital_twin.applied_perturbations")
    if dependencies:
        raise ValueError("cannot remove referenced spacecraft; resolve dependencies first: " + ", ".join(dependencies))
    satellites = tuple(item for item in source.constellation.satellites if item.satellite_id != satellite_id)
    if not satellites:
        raise ValueError("constellation must contain at least one spacecraft")
    constellation = ConstellationSpec(satellites=satellites, planes=_rebuild_planes(satellites, source.constellation.planes))
    return source.model_copy(update={"constellation": constellation})


def _move(source: ScenarioConfig, satellite_id: str, plane_id: str) -> ScenarioConfig:
    plane_id = plane_id.strip()
    if not plane_id:
        raise ValueError("plane_id must not be empty")
    found = False
    satellites = []
    for sat in source.constellation.satellites:
        if sat.satellite_id == satellite_id:
            sat = sat.model_copy(update={"plane_id": plane_id})
            found = True
        satellites.append(sat)
    if not found:
        raise ValueError(f"unknown satellite_id: {satellite_id}")
    satellites_tuple = tuple(satellites)
    constellation = ConstellationSpec(satellites=satellites_tuple, planes=_rebuild_planes(satellites_tuple, source.constellation.planes))
    return source.model_copy(update={"constellation": constellation})


def _edit(source: ScenarioConfig, request: ConstellationEditRequest) -> ScenarioConfig:
    found = False
    satellites = []
    known_ids = {sat.satellite_id for sat in source.constellation.satellites}
    for sat in source.constellation.satellites:
        if sat.satellite_id == request.satellite_id:
            update: dict[str, object] = {}
            if request.role is not None:
                update["role"] = request.role
            if request.reference_id is not None:
                if request.reference_id and request.reference_id not in known_ids:
                    raise ValueError(f"unknown reference_id: {request.reference_id}")
                update["reference_id"] = request.reference_id or None
            if request.spacecraft is not None:
                update["spacecraft"] = request.spacecraft
            sat = sat.model_copy(update=update)
            found = True
        satellites.append(sat)
    if not found:
        raise ValueError(f"unknown satellite_id: {request.satellite_id}")
    constellation = ConstellationSpec(satellites=tuple(satellites), planes=_rebuild_planes(tuple(satellites), source.constellation.planes))
    return source.model_copy(update={"constellation": constellation})


def _clone(source: ScenarioConfig, request: ConstellationEditRequest) -> ScenarioConfig:
    template = next((sat for sat in source.constellation.satellites if sat.satellite_id == request.satellite_id), None)
    if template is None:
        raise ValueError(f"unknown template satellite_id: {request.satellite_id}")
    new_id = (request.new_satellite_id or "").strip()
    if not new_id:
        raise ValueError("new_satellite_id is required for clone")
    if any(sat.satellite_id == new_id for sat in source.constellation.satellites):
        raise ValueError(f"satellite_id already exists: {new_id}")
    plane_id = (request.plane_id or template.plane_id).strip()
    clone = template.model_copy(update={
        "satellite_id": new_id,
        "plane_id": plane_id,
        "role": request.role or "additional",
        "reference_id": request.reference_id if request.reference_id is not None else template.satellite_id,
        "spacecraft": request.spacecraft or template.spacecraft,
    })
    satellites = source.constellation.satellites + (clone,)
    constellation = ConstellationSpec(satellites=satellites, planes=_rebuild_planes(satellites, source.constellation.planes))
    return source.model_copy(update={"constellation": constellation})


def apply_constellation_edit(root: Path, request: ConstellationEditRequest) -> dict[str, object]:
    source = load_scenario(root / request.source_scenario_name)
    if request.new_scenario_id == source.scenario_id:
        raise ValueError("new_scenario_id must differ from parent scenario_id")
    if request.operation == "rename":
        edited = _rename(source, request.satellite_id, request.new_satellite_id or "")
    elif request.operation == "remove":
        edited = _remove(source, request.satellite_id)
    elif request.operation == "move":
        edited = _move(source, request.satellite_id, request.plane_id or "")
    elif request.operation == "edit":
        edited = _edit(source, request)
    elif request.operation == "clone":
        edited = _clone(source, request)
    else:
        raise ValueError(f"unsupported operation: {request.operation}")

    child = _with_lineage(source, edited.constellation, edited.digital_twin, request.new_scenario_id)
    if edited.maneuvers != source.maneuvers:
        child = child.model_copy(update={"maneuvers": edited.maneuvers})
    # Revalidate after every cross-reference migration.
    child = ScenarioConfig.model_validate(child.model_dump(mode="json"))
    target = _target(root, request.target_scenario_name)
    target.write_text(yaml.safe_dump(child.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {
        "saved": True,
        "scenario_name": target.name,
        "scenario_id": child.scenario_id,
        "operation": request.operation,
        "parent_scenario_id": source.scenario_id,
        "parent_config_hash": source.config_hash(),
        "child_config_hash": child.config_hash(),
        "satellites": [sat.model_dump(mode="json") for sat in child.constellation.satellites],
    }


CONSTELLATION_EDITOR_CARD = r"""
<div class="card" id="constellationEditorCard">
  <h3>Состав орбитальной группировки / Constellation spacecraft editor</h3>
  <p class="hint">Добавление, переименование, удаление, перенос между плоскостями и редактирование физических параметров. Орбитальные элементы здесь не редактируются: для них используйте Orekit-authority input. Любое изменение создаёт новый derived scenario.</p>
  <div class="grid">
    <label>КА / Spacecraft <select id="ceSat"></select></label>
    <label>Новое имя / New ID <input id="ceNewId" type="text"></label>
    <label>Плоскость / Plane <input id="cePlane" type="text"></label>
    <label>Роль / Role <select id="ceRole"><option value="reference">reference</option><option value="additional">additional</option></select></label>
    <label>Опорный КА / Reference ID <input id="ceReference" type="text"></label>
  </div>
  <div class="grid">
    <label>Dry mass, kg <input id="ceDry" type="number" step="any"></label>
    <label>Fuel, kg <input id="ceFuel" type="number" step="any"></label>
    <label>Isp, s <input id="ceIsp" type="number" step="any"></label>
    <label>Area, m² <input id="ceArea" type="number" step="any"></label>
    <label>Cr <input id="ceCr" type="number" step="any"></label>
  </div>
  <div class="grid">
    <button onclick="ceApply('rename')">Переименовать / Rename</button>
    <button onclick="ceApply('move')">Переместить / Move</button>
    <button onclick="ceApply('edit')">Сохранить параметры / Edit</button>
    <button onclick="ceApply('clone')">Клонировать как новый КА / Clone as new</button>
    <button onclick="ceApply('remove')">Удалить / Remove</button>
  </div>
  <label>Новый scenario_id <input id="ceScenarioId" type="text" placeholder="derived-constellation-edit-01"></label>
  <label>Новый YAML <input id="ceScenarioFile" type="text" placeholder="derived-constellation-edit-01.yaml"></label>
  <pre id="cePreview"></pre><div id="ceStatus" class="status"></div>
</div>
"""

CONSTELLATION_EDITOR_SCRIPT = r"""
function syncConstellationEditor(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];ceSat.replaceChildren(...sats.map(s=>{const o=document.createElement('option');o.value=s.satellite_id;o.textContent=s.satellite_id;return o;}));if(sats.length){ceSat.value=sats[0].satellite_id;ceLoadSat();}}
function ceLoadSat(){if(!current)return;const sats=((current.normalized||current).constellation||{}).satellites||[];const s=sats.find(x=>x.satellite_id===ceSat.value);if(!s)return;ceNewId.value=s.satellite_id;cePlane.value=s.plane_id;ceRole.value=s.role;ceReference.value=s.reference_id||'';const m=s.spacecraft||{};ceDry.value=m.dry_mass_kg??'';ceFuel.value=m.propellant_mass_kg??'';ceIsp.value=m.isp_s??'';ceArea.value=m.area_m2??'';ceCr.value=m.cr??'';cePreview.textContent=JSON.stringify(s,null,2);}
ceSat?.addEventListener('change',ceLoadSat);
const cePriorLoadScenario=loadScenario;loadScenario=async function(){await cePriorLoadScenario();syncConstellationEditor();};
function ceNumber(id){const v=document.getElementById(id).value.trim();if(v==='')throw new Error(id+' is required');const n=Number(v);if(!Number.isFinite(n))throw new Error(id+' must be numeric');return n;}
async function ceApply(operation){const newScenarioId=ceScenarioId.value.trim(),target=ceScenarioFile.value.trim();if(!newScenarioId||!target){ceStatus.textContent='Укажите новый scenario_id и YAML';ceStatus.className='status danger';return;}const p={source_scenario_name:scenario.value,operation,satellite_id:ceSat.value,new_satellite_id:ceNewId.value.trim()||null,plane_id:cePlane.value.trim()||null,role:ceRole.value,reference_id:ceReference.value.trim(),target_scenario_name:target,new_scenario_id:newScenarioId};if(operation==='edit'||operation==='clone'){try{p.spacecraft={dry_mass_kg:ceNumber('ceDry'),propellant_mass_kg:ceNumber('ceFuel'),isp_s:ceNumber('ceIsp'),area_m2:ceNumber('ceArea'),cr:ceNumber('ceCr')};}catch(e){ceStatus.textContent=String(e.message||e);ceStatus.className='status danger';return;}}ceStatus.textContent='Validation…';const r=await fetch('/api/constellation-editor/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok){ceStatus.textContent=d.detail||'Edit failed';ceStatus.className='status danger';return;}cePreview.textContent=JSON.stringify(d,null,2);const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();ceStatus.textContent='Создан: '+d.scenario_name;ceStatus.className='status ok';}
"""


def install_constellation_editor_routes(app: FastAPI, scenario_root: Path = Path("scenarios")) -> None:
    @app.post("/api/constellation-editor/apply")
    def apply(request: ConstellationEditRequest) -> dict[str, object]:
        try:
            return apply_constellation_edit(scenario_root, request)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
