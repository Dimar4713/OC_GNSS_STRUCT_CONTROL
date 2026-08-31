from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from constellation_control.application.run import load_scenario
from constellation_control.application.walker import (
    WalkerDeltaRequest,
    build_walker_constellation,
    create_walker_derived_scenario,
)


def _validate_source_name(scenario_root: Path, name: str) -> Path:
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise ValueError("source_scenario_name must be a YAML file name without path components")
    root = scenario_root.resolve()
    source = (root / name).resolve()
    if source.parent != root or not source.is_file():
        raise ValueError(f"source scenario not found: {name}")
    return source


def preview_walker(scenario_root: Path, request: WalkerDeltaRequest) -> dict[str, object]:
    source_path = _validate_source_name(scenario_root, request.source_scenario_name)
    source = load_scenario(source_path)
    constellation = build_walker_constellation(source, request)
    return {
        "valid": True,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "satellite_count": len(constellation.satellites),
        "plane_count": len(constellation.planes),
        "satellites": [
            {
                "satellite_id": sat.satellite_id,
                "plane_id": sat.plane_id,
                "a_m": sat.mean_orbit.a_m,
                "ex": sat.mean_orbit.ex,
                "ey": sat.mean_orbit.ey,
                "ix": sat.mean_orbit.ix,
                "iy": sat.mean_orbit.iy,
                "lambda_rad": sat.mean_orbit.lambda_rad,
            }
            for sat in constellation.satellites
        ],
    }


def create_walker(scenario_root: Path, request: WalkerDeltaRequest) -> dict[str, object]:
    _validate_source_name(scenario_root, request.source_scenario_name)
    return create_walker_derived_scenario(scenario_root, request)


WALKER_CARD = r"""
<div class="card" id="walkerCard">
  <h3>Генератор Walker Delta / Walker Delta generator</h3>
  <p class="hint">Все геометрические параметры задаются явно. Формируется новая проектная mean-геометрия ОГ; исходный сценарий не изменяется. / All geometry inputs are explicit. Creates a new project mean-geometry constellation; the source scenario is not modified.</p>
  <div class="grid">
    <label>Новый scenario_id / New scenario_id<input id="walkerScenarioId" type="text" placeholder="walker-24-3-1"></label>
    <label>Новый YAML / New YAML<input id="walkerScenarioName" type="text" placeholder="walker-24-3-1.yaml"></label>
    <label>КА-шаблон / Template spacecraft ID<input id="walkerTemplate" type="text" placeholder="required"></label>
    <label>T — всего КА / total<input id="walkerT" type="number" min="1" placeholder="required"></label>
    <label>P — плоскостей / planes<input id="walkerP" type="number" min="1" placeholder="required"></label>
    <label>F — фазировка / phasing<input id="walkerF" type="number" min="0" placeholder="required"></label>
    <label>a, м / semi-major axis<input id="walkerA" type="number" min="1" step="1" placeholder="required"></label>
    <label>e<input id="walkerE" type="number" min="0" max="0.999999" step="0.0001" placeholder="required"></label>
    <label>i, град / deg<input id="walkerI" type="number" min="0" max="179.999999" step="0.01" placeholder="required"></label>
    <label>RAAN₀, град / deg<input id="walkerRaan0" type="number" step="0.01" placeholder="required"></label>
    <label>ω, град / deg<input id="walkerOmega" type="number" step="0.01" placeholder="required"></label>
    <label>M₀, град / deg<input id="walkerM0" type="number" step="0.01" placeholder="required"></label>
  </div>
  <button onclick="previewWalker()">Проверить геометрию / Preview geometry</button>
  <button onclick="createWalkerScenario()">Создать производный сценарий / Create derived scenario</button>
  <div id="walkerStatus" class="status">Задайте все параметры Walker / Enter all Walker parameters.</div>
  <div id="walkerSummary" class="table-wrap"></div>
</div>
"""


WALKER_SCRIPT = r"""
function walkerMessage(text,kind=''){const e=document.getElementById('walkerStatus');e.textContent=text;e.className='status '+kind;}
function walkerNumber(id,label){const raw=document.getElementById(id).value.trim();if(raw==='')throw new Error(label+' is required');const value=Number(raw);if(!Number.isFinite(value))throw new Error(label+' must be finite');return value;}
function walkerPayload(){
  const template=document.getElementById('walkerTemplate').value.trim();
  if(!template)throw new Error('template spacecraft ID is required');
  return {
    source_scenario_name:scenario.value,
    target_scenario_name:document.getElementById('walkerScenarioName').value.trim(),
    new_scenario_id:document.getElementById('walkerScenarioId').value.trim(),
    template_satellite_id:template,
    total_satellites:walkerNumber('walkerT','T'),
    planes:walkerNumber('walkerP','P'),
    phasing:walkerNumber('walkerF','F'),
    semi_major_axis_m:walkerNumber('walkerA','a'),
    eccentricity:walkerNumber('walkerE','e'),
    inclination_deg:walkerNumber('walkerI','i'),
    raan0_deg:walkerNumber('walkerRaan0','RAAN0'),
    argument_of_perigee_deg:walkerNumber('walkerOmega','omega'),
    mean_anomaly0_deg:walkerNumber('walkerM0','M0')
  };
}
function renderWalker(d){
  const rows=d.satellites.slice(0,24).map(s=>`<tr><td>${s.satellite_id}</td><td>${s.plane_id}</td><td>${s.a_m}</td><td>${s.lambda_rad.toFixed(6)}</td></tr>`).join('');
  document.getElementById('walkerSummary').innerHTML=`<p><b>КА:</b> ${d.satellite_count}; <b>плоскости:</b> ${d.plane_count}<br><span class="hint">Parent hash: ${d.source_config_hash}</span></p><table><thead><tr><th>КА</th><th>Плоскость</th><th>a, м</th><th>λ, rad</th></tr></thead><tbody>${rows}</tbody></table>`;
}
async function previewWalker(){
  if(!scenario.value){walkerMessage('Сначала выберите сценарий / Select a source scenario','danger');return;}
  let p;try{p=walkerPayload();}catch(e){walkerMessage(String(e.message||e),'danger');return;}
  walkerMessage('Проверка Walker… / Validating Walker…');
  const r=await fetch('/api/walker/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  const d=await r.json();
  if(!r.ok){walkerMessage(d.detail||'Walker validation failed','danger');return;}
  renderWalker(d);walkerMessage('VALID: геометрия сформирована без записи / geometry previewed without writing','ok');
}
async function createWalkerScenario(){
  let p;try{p=walkerPayload();}catch(e){walkerMessage(String(e.message||e),'danger');return;}
  if(!p.new_scenario_id||!p.target_scenario_name){walkerMessage('Укажите новый scenario_id и YAML / Supply new scenario_id and YAML','danger');return;}
  walkerMessage('Создание производного сценария… / Creating derived scenario…');
  const r=await fetch('/api/walker/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  const d=await r.json();
  if(!r.ok){walkerMessage(d.detail||'Walker creation failed','danger');return;}
  const c=await fetch('/api/scenarios');catalog=await c.json();
  scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));
  scenario.value=d.scenario_name;await loadScenario();
  walkerMessage(`Создано: ${d.scenario_name}; child hash=${d.child_config_hash} / created derived scenario`,'ok');
}
"""


def install_walker_routes(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/walker/preview")
    def walker_preview_route(request: WalkerDeltaRequest) -> dict[str, object]:
        try:
            return preview_walker(scenario_root, request)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/walker/create")
    def walker_create_route(request: WalkerDeltaRequest) -> dict[str, object]:
        try:
            return create_walker(scenario_root, request)
        except (ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
