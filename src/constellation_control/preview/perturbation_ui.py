from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.application.run import load_scenario
from constellation_control.domain.digital_twin import PerturbationRule
from constellation_control.preview.perturbation_input import apply_perturbation_rules, create_perturbed_scenario


class PerturbationPreviewRequest(BaseModel):
    source_scenario_name: str
    seed: int
    rules: tuple[PerturbationRule, ...]


class PerturbationCreateRequest(PerturbationPreviewRequest):
    target_scenario_name: str
    new_scenario_id: str


def _source(root: Path, name: str):
    if not name or Path(name).name != name or not name.lower().endswith((".yaml", ".yml")):
        raise ValueError("source_scenario_name must be a YAML file name without path components")
    base = root.resolve()
    path = (base / name).resolve()
    if path.parent != base or not path.is_file():
        raise ValueError("source scenario does not exist inside scenario root")
    return load_scenario(path)


def preview_perturbations(root: Path, request: PerturbationPreviewRequest) -> dict[str, object]:
    if not request.rules:
        raise ValueError("at least one enabled perturbation rule is required")
    source = _source(root, request.source_scenario_name)
    satellites, applied = apply_perturbation_rules(source, rules=request.rules, seed=request.seed)
    return {
        "valid": True,
        "source_scenario_id": source.scenario_id,
        "source_config_hash": source.config_hash(),
        "seed": request.seed,
        "satellite_count": len(satellites),
        "applied_count": len(applied),
        "applied_perturbations": [item.model_dump(mode="json") for item in applied],
    }


PERTURBATION_CARD = r"""
<div class="card" id="perturbationCard">
  <h3>Возмущения ОГ / Constellation perturbations</h3>
  <p class="hint">Каждая включённая строка требует явных M, закона распределения и области применения. Gaussian требует σ; Uniform требует нижнюю и верхнюю границы. Приоритет: КА &gt; группа &gt; плоскость &gt; вся ОГ. Seed обязателен. Цели выбираются только из открытого сценария. Исходный сценарий не перезаписывается.</p>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>Применять</th><th>Параметр</th><th>M</th><th>СКО σ</th><th>Закон</th><th>Нижняя</th><th>Верхняя</th><th>Единицы</th><th>Область</th><th>КА/группа/плоскость</th></tr></thead>
    <tbody id="pertRows"></tbody>
  </table></div>
  <label>Seed <input id="pertSeed" type="number" step="1" placeholder="обязательно / required"></label>
  <button onclick="previewPerturbations()">Предпросмотр выборки / Preview samples</button>
  <pre id="pertPreview"></pre>
  <label>Новый scenario_id <input id="pertScenarioId" type="text" placeholder="perturbed-scenario-01"></label>
  <label>Новый YAML <input id="pertFile" type="text" placeholder="perturbed-scenario-01.yaml"></label>
  <button onclick="createPerturbations()">Создать производный сценарий / Create derived scenario</button>
  <div id="pertStatus" class="status"></div>
</div>
"""

PERTURBATION_SCRIPT = r"""
const pertDefs=[
 ['a_m','Большая полуось / Semi-major axis','m'],
 ['e','Эксцентриситет / Eccentricity','1'],
 ['i_rad','Наклонение / Inclination','rad'],
 ['raan_rad','Ω / RAAN','rad'],
 ['argp_rad','ω / Argument of perigee','rad'],
 ['mean_anomaly_rad','Средняя аномалия / Mean anomaly','rad']
];
function perturbationCatalog(){
 const normalized=(current&&current.normalized)?current.normalized:current;
 const constellation=(normalized&&normalized.constellation)||{};
 const sats=constellation.satellites||[];
 const twin=(normalized&&normalized.digital_twin)||{};
 return {
   satellite:[...new Set(sats.map(s=>s.satellite_id))].sort(),
   plane:[...new Set(sats.map(s=>s.plane_id))].sort(),
   group:[...new Set((twin.groups||[]).map(g=>g.group_id))].sort()
 };
}
function populatePerturbationTarget(tr){
 const scope=tr.querySelector('.pc').value;
 const select=tr.querySelector('.pt');
 const previous=new Set([...select.selectedOptions].map(o=>o.value));
 select.replaceChildren();
 if(scope===''){
   const o=document.createElement('option');o.value='';o.textContent='Сначала выберите область / select scope first';o.disabled=true;select.appendChild(o);select.disabled=true;return;
 }
 if(scope==='constellation'){
   const o=document.createElement('option');o.value='';o.textContent='Вся ОГ / whole constellation';o.selected=true;select.appendChild(o);select.disabled=true;return;
 }
 select.disabled=false;
 const values=perturbationCatalog()[scope]||[];
 for(const value of values){const o=document.createElement('option');o.value=value;o.textContent=value;o.selected=previous.has(value);select.appendChild(o);}
 if(!values.length){const o=document.createElement('option');o.value='';o.textContent='Нет доступных целей / no targets';o.disabled=true;select.appendChild(o);}
}
function syncPerturbationTargets(){for(const tr of document.querySelectorAll('#pertRows tr'))populatePerturbationTarget(tr);}
function initPerturbationRows(){
 const body=document.getElementById('pertRows'); if(!body||body.children.length)return;
 for(const [p,label,u] of pertDefs){const tr=document.createElement('tr');tr.dataset.parameter=p;tr.dataset.unit=u;tr.innerHTML=`<td><input class="pe" type="checkbox"></td><td>${label}</td><td><input class="pm" type="number" step="any" placeholder="обязательно"></td><td><input class="ps" type="number" step="any" min="0"></td><td><select class="pd"><option value="">— выбрать —</option><option value="gaussian">Gaussian</option><option value="uniform">Uniform</option></select></td><td><input class="pl" type="number" step="any"></td><td><input class="pu" type="number" step="any"></td><td>${u}</td><td><select class="pc"><option value="">— выбрать область —</option><option value="constellation">Вся ОГ</option><option value="plane">Плоскость</option><option value="group">Группа</option><option value="satellite">КА</option></select></td><td><select class="pt" multiple size="3" style="min-width:150px"></select></td>`;tr.querySelector('.pc').addEventListener('change',()=>populatePerturbationTarget(tr));body.appendChild(tr);populatePerturbationTarget(tr);}
}
function perturbationPayload(){
 const seedText=document.getElementById('pertSeed').value.trim();if(seedText==='')throw new Error('Seed обязателен / Seed is required');
 const rules=[];let n=0;
 for(const tr of document.querySelectorAll('#pertRows tr')){if(!tr.querySelector('.pe').checked)continue;n++;const parameter=tr.dataset.parameter,unit=tr.dataset.unit;const meanText=tr.querySelector('.pm').value.trim(),distribution=tr.querySelector('.pd').value,scope=tr.querySelector('.pc').value;if(!scope)throw new Error('Для каждой включённой строки выберите область / Select scope for every enabled row');const target_ids=scope==='constellation'?[]:[...tr.querySelector('.pt').selectedOptions].map(o=>o.value).filter(Boolean);if(meanText===''||!distribution)throw new Error('Для каждой включённой строки задайте M и закон / Set M and distribution for every enabled row');if(scope!=='constellation'&&!target_ids.length)throw new Error('Выберите хотя бы одну цель для области '+scope+' / Select at least one target');const rule={rule_id:`ui-${parameter}-${n}`,parameter,distribution,scope,target_ids,mean:+meanText,unit};if(distribution==='gaussian'){const s=tr.querySelector('.ps').value.trim();if(s==='')throw new Error('Gaussian требует σ / Gaussian requires sigma');rule.sigma=+s;}else{const l=tr.querySelector('.pl').value.trim(),u=tr.querySelector('.pu').value.trim();if(l===''||u==='')throw new Error('Uniform требует нижнюю и верхнюю границы / Uniform requires bounds');rule.lower_bound=+l;rule.upper_bound=+u;}rules.push(rule);}
 if(!rules.length)throw new Error('Включите хотя бы одно возмущение / Enable at least one perturbation');return {source_scenario_name:scenario.value,seed:+seedText,rules};
}
async function previewPerturbations(){try{const p=perturbationPayload();pertStatus.textContent='Sampling…';const r=await fetch('/api/perturbations/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Preview failed');pertPreview.textContent=JSON.stringify(d,null,2);pertStatus.textContent='VALID: applied='+d.applied_count+'; seed='+d.seed;pertStatus.className='status ok';}catch(e){pertStatus.textContent=String(e.message||e);pertStatus.className='status danger';}}
async function createPerturbations(){try{const p=perturbationPayload();p.new_scenario_id=pertScenarioId.value.trim();p.target_scenario_name=pertFile.value.trim();if(!p.new_scenario_id||!p.target_scenario_name)throw new Error('Укажите новый scenario_id и YAML');const r=await fetch('/api/perturbations/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Create failed');const c=await fetch('/api/scenarios');catalog=await c.json();scenario.replaceChildren(...catalog.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o;}));scenario.value=d.scenario_name;await loadScenario();pertPreview.textContent=JSON.stringify(d,null,2);pertStatus.textContent='Создан: '+d.scenario_name+'; applied='+d.applied_count;pertStatus.className='status ok';}catch(e){pertStatus.textContent=String(e.message||e);pertStatus.className='status danger';}}
initPerturbationRows();
const loadScenarioBeforePerturbationTargets=loadScenario;
loadScenario=async function(){await loadScenarioBeforePerturbationTargets();syncPerturbationTargets();};
"""


def install_perturbation_routes(app: FastAPI, scenario_root: Path) -> None:
    @app.post("/api/perturbations/preview")
    def preview(request: PerturbationPreviewRequest) -> dict[str, object]:
        try:
            return preview_perturbations(scenario_root, request)
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/perturbations/create")
    def create(request: PerturbationCreateRequest) -> dict[str, object]:
        try:
            return create_perturbed_scenario(
                scenario_root,
                source_scenario_name=request.source_scenario_name,
                target_scenario_name=request.target_scenario_name,
                new_scenario_id=request.new_scenario_id,
                rules=request.rules,
                seed=request.seed,
            )
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
