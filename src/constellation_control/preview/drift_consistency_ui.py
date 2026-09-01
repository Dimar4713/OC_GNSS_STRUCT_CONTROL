from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

from constellation_control.preview.result_paths import safe_result_file


DRIFT_CONSISTENCY_CARD = r"""
<div class="card" id="driftConsistencyCard">
  <h3>Физическая проверка дрейфа / Drift physical consistency</h3>
  <p class="hint">Показывает независимую цепочку deputy − reference: mean a → Kepler period → central-field Δn → measured Orekit Δλ and Δu=λ−Ω. Kepler Δn — baseline, а не требование равенства full-force rates.</p>
  <label for="driftRunScenario"><b>Scenario ID</b></label>
  <input id="driftRunScenario" type="text" placeholder="scenario-id">
  <label for="driftRunId"><b>Run ID</b></label>
  <input id="driftRunId" type="text" placeholder="run-id">
  <button onclick="loadDriftConsistency()">Загрузить проверку / Load check</button>
  <label for="driftPair"><b>Пара КА / Satellite pair</b></label>
  <select id="driftPair" onchange="renderDriftPair()"></select>
  <div id="driftConsistencyStatus" class="status">Выберите завершённый run с kepler_drift_consistency.json.</div>
  <div id="driftConsistencyTable"></div>
  <div id="driftConsistencyLinks"></div>
</div>
"""


DRIFT_CONSISTENCY_SCRIPT = r"""
let driftConsistencyRows=[];
function driftFmt(v,d=9){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'—';}
async function loadDriftConsistency(){
  const sid=document.getElementById('driftRunScenario').value.trim();
  const rid=document.getElementById('driftRunId').value.trim();
  const status=document.getElementById('driftConsistencyStatus');
  if(!sid||!rid){status.textContent='Укажите scenario_id и run_id / Supply scenario_id and run_id';status.className='status danger';return;}
  const r=await fetch('/api/drift-consistency/'+encodeURIComponent(sid)+'/'+encodeURIComponent(rid));
  const d=await r.json();
  if(!r.ok){status.textContent=d.detail||'Cannot load drift consistency';status.className='status danger';return;}
  driftConsistencyRows=d.rows||[];
  const sel=document.getElementById('driftPair');sel.replaceChildren(...driftConsistencyRows.map((x,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=x.pair_id;return o;}));
  status.textContent=driftConsistencyRows.length?'Знак: deputy − reference. Central-field baseline only.':'Нет additional/reference pair / No pair';status.className='status '+(driftConsistencyRows.length?'ok':'');
  document.getElementById('driftConsistencyLinks').innerHTML='<a target="_blank" href="'+d.report_url+'">kepler_drift_consistency.html</a>';
  renderDriftPair();
}
function renderDriftPair(){
  const sel=document.getElementById('driftPair');const x=driftConsistencyRows[Number(sel.value||0)];const out=document.getElementById('driftConsistencyTable');
  if(!x){out.innerHTML='';return;}
  const da0=Number(x.deputy_initial_a_mean_m)-Number(x.reference_initial_a_mean_m);
  const dam=Number(x.deputy_time_mean_a_mean_m)-Number(x.reference_time_mean_a_mean_m);
  out.innerHTML='<table><tbody>'+
    '<tr><th>Pair</th><td>'+x.pair_id+'</td></tr>'+
    '<tr><th>Δa initial, m</th><td>'+driftFmt(da0,6)+'</td></tr>'+
    '<tr><th>Δa time-mean, m</th><td>'+driftFmt(dam,6)+'</td></tr>'+
    '<tr><th>T ref / dep initial, s</th><td>'+driftFmt(x.reference_initial_kepler_period_s,6)+' / '+driftFmt(x.deputy_initial_kepler_period_s,6)+'</td></tr>'+
    '<tr><th>ΔT initial, s</th><td>'+driftFmt(x.initial_period_difference_s,9)+'</td></tr>'+
    '<tr><th>Kepler Δn initial, rad/s</th><td>'+driftFmt(x.initial_kepler_delta_n_rad_s,12)+'</td></tr>'+
    '<tr><th>Kepler Δn time-mean, deg/day</th><td>'+driftFmt(x.time_mean_kepler_delta_n_deg_day,9)+'</td></tr>'+
    '<tr><th>Measured Orekit Δλ, deg/day</th><td>'+driftFmt(x.measured_delta_lambda_rate_deg_day,9)+'</td></tr>'+
    '<tr><th>Measured Orekit Δu=λ−Ω, deg/day</th><td>'+driftFmt(x.measured_delta_u_rate_deg_day,9)+'</td></tr>'+
    '<tr><th>Δλ − Kepler, deg/day</th><td>'+driftFmt(x.delta_lambda_minus_kepler_deg_day,9)+'</td></tr>'+
    '<tr><th>Δu − Kepler, deg/day</th><td>'+driftFmt(x.delta_u_minus_kepler_deg_day,9)+'</td></tr>'+
    '</tbody></table><p class="hint">'+x.semantics+'</p>';
}
"""


def install_drift_consistency_routes(app: FastAPI, output_root: Path) -> None:
    @app.get('/api/drift-consistency/{scenario_id}/{run_id}')
    def drift_consistency(scenario_id: str, run_id: str) -> dict[str, object]:
        try:
            json_path = safe_result_file(output_root, scenario_id, run_id, 'kepler_drift_consistency.json')
            safe_result_file(output_root, scenario_id, run_id, 'kepler_drift_consistency.html')
            rows = json.loads(json_path.read_text(encoding='utf-8'))
            if not isinstance(rows, list):
                raise ValueError('kepler_drift_consistency.json must contain a JSON array')
            return {
                'rows': rows,
                'report_url': f'/results/{scenario_id}/{run_id}/kepler_drift_consistency.html',
            }
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
