from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ValidationError

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


def _safe_result_file(output_root: Path, scenario_id: str, run_id: str, name: str) -> Path:
    for component in (scenario_id, run_id, name):
        if not component or component in {".", ".."} or Path(component).name != component:
            raise ValueError("result path contains invalid components")
    root = output_root.resolve()
    candidate = (root / scenario_id / run_id / name).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError("result artifact not found")
    return candidate


def _classify_yaml(path: Path) -> tuple[str, str | None]:
    try:
        load_scenario(path)
        return "scenario", None
    except (ValidationError, ValueError, TypeError) as exc:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return "invalid_yaml", "YAML cannot be parsed"
        if isinstance(raw, dict):
            keys = set(raw)
            if {"bounds", "lhs_samples", "top_k"}.issubset(keys):
                return "design_pipeline_config", "Design pipeline configuration; use the Design workflow, not Run scenario."
            if "campaign" in keys:
                return "robustness_campaign_config", "Robustness campaign configuration; use the Robustness workflow, not Run scenario."
        first = str(exc).splitlines()[0] if str(exc) else "not a ScenarioConfig"
        return "other_yaml", first


def preview_catalog(scenario_root: Path) -> dict[str, object]:
    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    if not scenario_root.is_dir():
        return {"scenarios": accepted, "other_inputs": rejected}
    for path in sorted(scenario_root.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        kind, diagnostic = _classify_yaml(path)
        if kind == "scenario":
            accepted.append(path.name)
        else:
            rejected.append({"name": path.name, "kind": kind, "diagnostic": diagnostic or "not a runnable scenario"})
    return {"scenarios": accepted, "other_inputs": rejected}


def list_preview_scenarios(scenario_root: Path) -> list[str]:
    return list(preview_catalog(scenario_root)["scenarios"])


def _load_preview_scenario(scenario_root: Path, scenario_name: str) -> tuple[Path, ScenarioConfig]:
    path = _safe_scenario_path(scenario_root, scenario_name)
    kind, diagnostic = _classify_yaml(path)
    if kind != "scenario":
        raise ValueError(f"{scenario_name} is {kind}, not a runnable ScenarioConfig. {diagnostic or ''}".strip())
    return path, load_scenario(path)


def scenario_preview_payload(scenario_root: Path, scenario_name: str) -> dict[str, object]:
    path, scenario = _load_preview_scenario(scenario_root, scenario_name)
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


def authority_preflight(scenario: ScenarioConfig, timeout_s: float = 2.0) -> dict[str, object]:
    if scenario.force_model.mode == ForceMode.SCREENING:
        return {
            "ready": True,
            "authority": _authority_label(scenario),
            "reason": "local screening authority does not require the Orekit sidecar",
        }
    if not scenario.orekit_sidecar_url:
        return {
            "ready": False,
            "authority": _authority_label(scenario),
            "reason": "orekit_sidecar_url is not configured",
        }
    parsed = urlparse(scenario.orekit_sidecar_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "ready": False,
            "authority": _authority_label(scenario),
            "reason": "orekit_sidecar_url must be an explicit http(s) endpoint",
        }
    health_url = scenario.orekit_sidecar_url.rstrip("/") + "/healthz"
    try:
        with urlopen(health_url, timeout=timeout_s) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "ready": False,
            "authority": _authority_label(scenario),
            "reason": f"Orekit authority unavailable: {exc}",
        }
    data_sha = str(payload.get("orekit_data_sha256", ""))
    valid_sha = len(data_sha) == 64
    if valid_sha:
        try:
            int(data_sha, 16)
        except ValueError:
            valid_sha = False
    ready = payload.get("status") == "ok" and payload.get("backend") == "orekit" and valid_sha
    result: dict[str, object] = {
        "ready": ready,
        "authority": _authority_label(scenario),
        "backend": payload.get("backend"),
        "orekit_version": payload.get("orekit_version"),
        "orekit_data_revision": payload.get("orekit_data_revision"),
        "orekit_data_sha256": payload.get("orekit_data_sha256"),
    }
    if not ready:
        result["reason"] = "Orekit health response lacks complete authority metadata"
    return result


def _page() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OC GNSS STRUCT CONTROL — Engineering Preview 0.1</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#17202a}header{background:#17202a;color:white;padding:16px 24px}main{padding:20px;display:grid;grid-template-columns:300px 1fr;gap:18px}.card{background:white;border:1px solid #d9dee3;border-radius:8px;padding:16px;margin-bottom:14px}select,button{width:100%;padding:9px;margin-top:8px}.badge{display:inline-block;padding:6px 10px;border-radius:6px;background:#eef2f5;font-weight:700}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #e5e8eb;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}pre{white-space:pre-wrap;word-break:break-word;background:#111820;color:#d9e2ec;padding:12px;border-radius:6px;max-height:360px;overflow:auto}.status{padding:9px;border-radius:6px;background:#eef2f5;margin-top:10px}.danger{background:#ffe8e8}.ok{background:#e8f7ed}a.result{display:block;margin-top:10px;font-weight:700}@media(max-width:800px){main{grid-template-columns:1fr}}</style></head>
<body><header><b>OC GNSS STRUCT CONTROL — Engineering Preview 0.1</b><br><small>Local expert shell. Physics authority remains explicit and fail-closed.</small></header>
<main><aside><div class="card"><b>Scenario</b><select id="scenario"></select><button onclick="loadScenario()">Open scenario</button><button onclick="runScenario()">Run selected scenario</button><div id="status" class="status">Ready.</div><a id="result" class="result" target="_blank"></a></div><div class="card"><b>Authority</b><p id="authority" class="badge">—</p><p id="preflight">—</p><p id="physics"></p></div><div class="card"><b>Other YAML inputs</b><div id="other">—</div></div></aside>
<section><div class="card"><h2 id="title">Select a scenario</h2><div id="meta"></div></div><div class="card"><h3>Constellation</h3><div id="fleet"></div></div><div class="card"><h3>Expert / YAML</h3><pre id="yaml"></pre></div><div class="card"><h3>Normalized scenario</h3><pre id="normalized"></pre></div></section></main>
<script>const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function setStatus(t,k=''){const e=document.getElementById('status');e.textContent=t;e.className='status '+k}async function bootstrap(){const r=await fetch('/api/scenarios');const d=await r.json();const s=document.getElementById('scenario');s.replaceChildren(...d.scenarios.map(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;return o}));document.getElementById('other').innerHTML=d.other_inputs.length?d.other_inputs.map(x=>`<div><b>${esc(x.name)}</b><br><small>${esc(x.kind)} — ${esc(x.diagnostic)}</small></div>`).join('<hr>'):'None';if(d.scenarios.length)await loadScenario()}async function loadScenario(){const n=document.getElementById('scenario').value;if(!n)return;setStatus('Loading…');const r=await fetch('/api/scenarios/'+encodeURIComponent(n));const d=await r.json();if(!r.ok){setStatus(d.detail||'Load failed','danger');return}document.getElementById('title').textContent=d.scenario_id;document.getElementById('authority').textContent=d.authority;document.getElementById('physics').textContent=d.mean_element_rule;document.getElementById('meta').innerHTML=`Epoch: ${esc(d.epoch)}<br>Frame/time: ${esc(d.frame)} / ${esc(d.time_scale)}<br>Duration: ${esc(d.duration_s)} s; step: ${esc(d.output_step_s)} s<br>Force fingerprint: <code>${esc(d.force_model_fingerprint)}</code>`;document.getElementById('fleet').innerHTML=renderFleet(d.satellites);document.getElementById('yaml').textContent=d.yaml_text;document.getElementById('normalized').textContent=JSON.stringify(d.normalized,null,2);await loadPreflight(n);setStatus('Scenario validated.','ok')}async function loadPreflight(n){const r=await fetch('/api/preflight/'+encodeURIComponent(n));const d=await r.json();const e=document.getElementById('preflight');e.textContent=d.ready?'READY: '+(d.orekit_version?`Orekit ${d.orekit_version}`:d.reason):'NOT READY: '+(d.reason||'authority metadata incomplete');e.className=d.ready?'ok':'danger'}function renderFleet(rows){let h='<table><tr><th>Satellite</th><th>Plane</th><th>Role</th><th>Mean a, m</th><th>λ, rad</th><th>Mass, kg</th><th>Fuel, kg</th></tr>';for(const x of rows)h+=`<tr><td>${esc(x.satellite_id)}</td><td>${esc(x.plane_id)}</td><td>${esc(x.role)}</td><td>${esc(x.a_mean_m)}</td><td>${esc(x.lambda_rad)}</td><td>${esc(x.initial_mass_kg)}</td><td>${esc(x.propellant_mass_kg)}</td></tr>`;return h+'</table>'}async function runScenario(){const n=document.getElementById('scenario').value;if(!n)return;setStatus('Running scenario…');const r=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario_name:n})});const d=await r.json();if(!r.ok){setStatus(d.detail||'Run failed','danger');return}setStatus('Completed: '+d.run_dir,'ok');const a=document.getElementById('result');a.href=d.report_url;a.textContent='Open engineering report'}bootstrap().catch(e=>setStatus(String(e),'danger'));</script></body></html>"""


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = FastAPI(title="OC GNSS STRUCT CONTROL Engineering Preview", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_page())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "preview": "0.1"}

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, object]:
        return preview_catalog(scenario_root)

    @app.get("/api/scenarios/{scenario_name}")
    def scenario(scenario_name: str) -> dict[str, object]:
        try:
            return scenario_preview_payload(scenario_root, scenario_name)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/preflight/{scenario_name}")
    def preflight(scenario_name: str) -> dict[str, object]:
        try:
            _, loaded = _load_preview_scenario(scenario_root, scenario_name)
            return authority_preflight(loaded)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs")
    def run(request: PreviewRunRequest) -> dict[str, str]:
        try:
            scenario_path, _ = _load_preview_scenario(scenario_root, request.scenario_name)
            run_dir = run_scenario(scenario_path, output_root)
            relative = run_dir.resolve().relative_to(output_root.resolve())
            if len(relative.parts) != 2:
                raise RuntimeError("unexpected run directory layout")
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scenario_id, run_id = relative.parts
        return {"run_dir": str(run_dir), "report_url": f"/api/results/{scenario_id}/{run_id}/report.html"}

    @app.get("/api/results/{scenario_id}/{run_id}/report.html", response_class=FileResponse)
    def report(scenario_id: str, run_id: str) -> FileResponse:
        try:
            report_path = _safe_result_file(output_root, scenario_id, run_id, "report.html")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(report_path, media_type="text/html")

    return app


app = create_preview_app()


def render_preview_page_for_test() -> str:
    return _page()
