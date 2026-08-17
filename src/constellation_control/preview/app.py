from __future__ import annotations

import json
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from constellation_control.application.run import load_scenario, run_scenario
from constellation_control.domain.models import ForceMode, ScenarioConfig


class PreviewRunRequest(BaseModel):
    scenario_name: str


def _authority_label(scenario: ScenarioConfig) -> str:
    mode = scenario.force_model.mode
    if mode == ForceMode.SCREENING:
        return "SCREENING — analytical/synthetic mean-element authority"
    if mode == ForceMode.DESIGN:
        return "DESIGN — Orekit DSST authority required"
    if mode == ForceMode.VALIDATION:
        return "VALIDATION — Orekit numerical authority required"
    raise ValueError(f"unsupported force mode: {mode}")


def _safe_scenario_path(scenario_root: Path, scenario_name: str) -> Path:
    if not scenario_name or Path(scenario_name).name != scenario_name:
        raise ValueError("scenario_name must be a YAML file name without path components")
    if not scenario_name.lower().endswith((".yaml", ".yml")):
        raise ValueError("scenario_name must end with .yaml or .yml")
    root = scenario_root.resolve()
    candidate = (root / scenario_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise ValueError(f"scenario not found: {scenario_name}")
    return candidate


def list_preview_scenarios(scenario_root: Path) -> list[str]:
    if not scenario_root.is_dir():
        return []
    names = [path.name for path in scenario_root.iterdir() if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}]
    return sorted(names)


def scenario_preview_payload(scenario_root: Path, scenario_name: str) -> dict[str, object]:
    path = _safe_scenario_path(scenario_root, scenario_name)
    scenario = load_scenario(path)
    satellites = [
        {
            "satellite_id": satellite.satellite_id,
            "plane_id": satellite.plane_id,
            "role": satellite.role,
            "reference_id": satellite.reference_id,
            "a_mean_m": satellite.mean_orbit.a_m,
            "ex": satellite.mean_orbit.ex,
            "ey": satellite.mean_orbit.ey,
            "ix": satellite.mean_orbit.ix,
            "iy": satellite.mean_orbit.iy,
            "lambda_rad": satellite.mean_orbit.lambda_rad,
            "initial_mass_kg": satellite.spacecraft.initial_mass_kg,
            "propellant_mass_kg": satellite.spacecraft.propellant_mass_kg,
        }
        for satellite in scenario.constellation.satellites
    ]
    return {
        "scenario_name": scenario_name,
        "scenario_id": scenario.scenario_id,
        "authority": _authority_label(scenario),
        "force_mode": scenario.force_model.mode.value,
        "force_model_fingerprint": scenario.force_model.fingerprint(),
        "epoch": scenario.epoch.isoformat(),
        "frame": scenario.frame.value,
        "time_scale": scenario.time_scale.value,
        "duration_s": scenario.duration_s,
        "output_step_s": scenario.output_step_s,
        "satellites": satellites,
        "navigation_sites": [site.model_dump(mode="json") for site in scenario.navigation_sites],
        "normalized": scenario.model_dump(mode="json"),
        "yaml_text": path.read_text(encoding="utf-8"),
        "mean_element_rule": (
            "Secular behavior is evaluated from force-model-consistent mean elements; "
            "instantaneous osculating semi-major axis is not a secular control criterion."
        ),
    }


def _page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OC GNSS STRUCT CONTROL — Engineering Preview 0.1</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#17202a}
header{background:#17202a;color:white;padding:16px 24px} header small{opacity:.75}
main{padding:20px;display:grid;grid-template-columns:280px 1fr;gap:18px}
.card{background:white;border:1px solid #d9dee3;border-radius:8px;padding:16px;margin-bottom:14px}
select,button{width:100%;padding:9px;margin-top:8px} button{cursor:pointer;font-weight:600}
.badge{display:inline-block;padding:6px 10px;border-radius:6px;background:#eef2f5;font-weight:700}
table{border-collapse:collapse;width:100%;font-size:13px} th,td{border-bottom:1px solid #e5e8eb;padding:7px;text-align:right} th:first-child,td:first-child{text-align:left}
pre{white-space:pre-wrap;word-break:break-word;background:#111820;color:#d9e2ec;padding:12px;border-radius:6px;max-height:360px;overflow:auto}
.status{padding:9px;border-radius:6px;background:#eef2f5;margin-top:10px}.danger{background:#ffe8e8}.ok{background:#e8f7ed}
@media(max-width:800px){main{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><b>OC GNSS STRUCT CONTROL — Engineering Preview 0.1</b><br><small>Local expert shell. Physics authority remains explicit and fail-closed.</small></header>
<main>
<aside>
  <div class="card"><b>Scenario</b><select id="scenario"></select><button onclick="loadScenario()">Open scenario</button><button onclick="runScenario()">Run selected scenario</button><div id="status" class="status">Ready.</div></div>
  <div class="card"><b>Authority</b><p id="authority" class="badge">—</p><p id="physics"></p></div>
</aside>
<section>
  <div class="card"><h2 id="title">Select a scenario</h2><div id="meta"></div></div>
  <div class="card"><h3>Constellation</h3><div id="fleet"></div></div>
  <div class="card"><h3>Expert / YAML</h3><pre id="yaml"></pre></div>
  <div class="card"><h3>Normalized scenario</h3><pre id="normalized"></pre></div>
</section>
</main>
<script>
let current=null;
function setStatus(text,kind=''){const e=document.getElementById('status');e.textContent=text;e.className='status '+kind;}
async function bootstrap(){const r=await fetch('/api/scenarios');const d=await r.json();const s=document.getElementById('scenario');s.innerHTML=d.scenarios.map(x=>`<option>${x}</option>`).join('');if(d.scenarios.length){await loadScenario();}}
async function loadScenario(){const name=document.getElementById('scenario').value;if(!name)return;setStatus('Loading…');const r=await fetch('/api/scenarios/'+encodeURIComponent(name));const d=await r.json();if(!r.ok){setStatus(d.detail||'Load failed','danger');return;}current=d;document.getElementById('title').textContent=d.scenario_id;document.getElementById('authority').textContent=d.authority;document.getElementById('physics').textContent=d.mean_element_rule;document.getElementById('meta').innerHTML=`Epoch: ${d.epoch}<br>Frame/time: ${d.frame} / ${d.time_scale}<br>Duration: ${d.duration_s} s; step: ${d.output_step_s} s<br>Force fingerprint: <code>${d.force_model_fingerprint}</code>`;document.getElementById('fleet').innerHTML=renderFleet(d.satellites);document.getElementById('yaml').textContent=d.yaml_text;document.getElementById('normalized').textContent=JSON.stringify(d.normalized,null,2);setStatus('Scenario validated.','ok');}
function renderFleet(rows){let h='<table><tr><th>Satellite</th><th>Plane</th><th>Role</th><th>Mean a, m</th><th>λ, rad</th><th>Mass, kg</th><th>Fuel, kg</th></tr>';for(const x of rows){h+=`<tr><td>${x.satellite_id}</td><td>${x.plane_id}</td><td>${x.role}</td><td>${x.a_mean_m}</td><td>${x.lambda_rad}</td><td>${x.initial_mass_kg}</td><td>${x.propellant_mass_kg}</td></tr>`;}return h+'</table>';}
async function runScenario(){const name=document.getElementById('scenario').value;if(!name)return;setStatus('Running scenario…');const r=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_name:name})});const d=await r.json();if(!r.ok){setStatus(d.detail||'Run failed','danger');return;}setStatus('Completed: '+d.run_dir,'ok');}
bootstrap().catch(e=>setStatus(String(e),'danger'));
</script>
</body></html>"""


def create_preview_app(
    scenario_root: Path = Path("scenarios"),
    output_root: Path = Path("runs"),
) -> FastAPI:
    app = FastAPI(title="OC GNSS STRUCT CONTROL Engineering Preview", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_page())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "preview": "0.1"}

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, list[str]]:
        return {"scenarios": list_preview_scenarios(scenario_root)}

    @app.get("/api/scenarios/{scenario_name}")
    def scenario(scenario_name: str) -> dict[str, object]:
        try:
            return scenario_preview_payload(scenario_root, scenario_name)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/runs")
    def run(request: PreviewRunRequest) -> dict[str, str]:
        try:
            scenario_path = _safe_scenario_path(scenario_root, request.scenario_name)
            run_dir = run_scenario(scenario_path, output_root)
        except Exception as exc:
            # High-fidelity authority errors intentionally propagate to the UI as a failed run.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"run_dir": str(run_dir)}

    return app


# Default local application for `uvicorn constellation_control.preview.app:app`.
app = create_preview_app()


def render_preview_page_for_test() -> str:
    """Expose deterministic shell markup without starting an HTTP server."""
    return escape(_page(), quote=False)
