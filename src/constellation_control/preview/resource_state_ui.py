from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.application.resource_snapshot import (
    build_operational_resource_snapshot,
    save_operational_resource_snapshot,
)
from constellation_control.application.run import load_scenario


class ResourceStateRequest(BaseModel):
    source_scenario_name: str


class ResourceSnapshotRequest(ResourceStateRequest):
    snapshot_name: str


def _source(root: Path, name: str):
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise ValueError("source_scenario_name must be a YAML file name without path components")
    base = root.resolve()
    path = (base / name).resolve()
    if path.parent != base or not path.is_file():
        raise ValueError("source scenario does not exist inside scenario root")
    return load_scenario(path)


RESOURCE_STATE_CARD = r"""
<div class="card" id="resourceStateCard">
  <h3>Масса и топливо КА / Spacecraft mass & propellant</h3>
  <p class="hint">Показывается плановое состояние ресурсов после всех манёвров выбранного сценария. Это не перенос орбитальной эпохи: snapshot хранится отдельно и не подменяет ScenarioConfig.</p>
  <button onclick="previewResourceState()">Обновить таблицу / Refresh resource state</button>
  <div style="overflow-x:auto"><table><thead><tr><th>КА</th><th>Масса, кг</th><th>Топливо, кг</th><th>Расход, кг</th><th>ΔV, м/с</th><th>Isp, с</th><th>Authority</th></tr></thead><tbody id="resourceStateRows"></tbody></table></div>
  <label>Имя snapshot YAML <input id="resourceSnapshotName" type="text" placeholder="resource-state-01.yaml"></label>
  <button onclick="saveResourceSnapshot()">Сохранить immutable snapshot / Save snapshot</button>
  <div id="resourceStateStatus" class="status"></div>
  <pre id="resourceStateHistory"></pre>
</div>
"""

RESOURCE_STATE_SCRIPT = r"""
function renderResourceState(d){
 const body=document.getElementById('resourceStateRows');body.replaceChildren();
 const history=d.maneuver_resource_history||[];
 const finalBy={};for(const row of history)finalBy[row.satellite_id]=row;
 for(const state of (d.spacecraft_states||[])){const row=finalBy[state.satellite_id]||{};const tr=document.createElement('tr');tr.innerHTML=`<td>${state.satellite_id}</td><td>${Number(state.current_mass_kg).toFixed(6)}</td><td>${Number(state.current_propellant_mass_kg).toFixed(6)}</td><td>${Number(row.propellant_used_kg||0).toFixed(6)}</td><td>${Number(row.cumulative_delta_v_m_s||0).toFixed(6)}</td><td>${Number(row.isp_s||0).toFixed(3)}</td><td>${row.isp_authority||''}</td>`;body.appendChild(tr);}
 document.getElementById('resourceStateHistory').textContent=JSON.stringify(history,null,2);
}
async function previewResourceState(){try{resourceStateStatus.textContent='Расчёт ресурсов…';const r=await fetch('/api/resource-state/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_scenario_name:scenario.value})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Preview failed');renderResourceState(d);resourceStateStatus.textContent='VALID: '+d.source_scenario_id+'; t='+d.snapshot_time_s+' s';resourceStateStatus.className='status ok';}catch(e){resourceStateStatus.textContent=String(e.message||e);resourceStateStatus.className='status danger';}}
async function saveResourceSnapshot(){try{const name=resourceSnapshotName.value.trim();if(!name)throw new Error('Укажите имя snapshot YAML');const r=await fetch('/api/resource-state/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_scenario_name:scenario.value,snapshot_name:name})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Save failed');renderResourceState(d.snapshot);resourceStateStatus.textContent='Snapshot сохранён: '+d.snapshot_name;resourceStateStatus.className='status ok';}catch(e){resourceStateStatus.textContent=String(e.message||e);resourceStateStatus.className='status danger';}}
"""


def install_resource_state_routes(app: FastAPI, scenario_root: Path, output_root: Path) -> None:
    @app.post("/api/resource-state/preview")
    def preview(request: ResourceStateRequest) -> dict[str, object]:
        try:
            return build_operational_resource_snapshot(_source(scenario_root, request.source_scenario_name))
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/resource-state/save")
    def save(request: ResourceSnapshotRequest) -> dict[str, object]:
        try:
            source = _source(scenario_root, request.source_scenario_name)
            path = save_operational_resource_snapshot(source, output_root, request.snapshot_name)
            return {"saved": True, "snapshot_name": path.name, "snapshot": build_operational_resource_snapshot(source)}
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
