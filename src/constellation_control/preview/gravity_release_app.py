from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from constellation_control.preview.consolidated_release_app import (
    create_preview_app as create_consolidated_preview_app,
    render_preview_page_for_test as render_consolidated_page,
)
from constellation_control.preview.gravity_model_ui import (
    GRAVITY_MODEL_CARD,
    GRAVITY_MODEL_SCRIPT,
    install_gravity_model_routes,
)


def render_preview_page_for_test() -> str:
    page = render_consolidated_page()
    page = page.replace("</section></main>", f"{GRAVITY_MODEL_CARD}</section></main>", 1)
    page = page.replace(
        "bootstrap().catch(e=>setStatus(String(e),'danger'));",
        f"{GRAVITY_MODEL_SCRIPT}\nconst gravityBootstrap=bootstrap;bootstrap=async function(){{await gravityBootstrap();if(typeof syncGravityModel==='function')syncGravityModel();}};bootstrap().catch(e=>setStatus(String(e),'danger'));",
        1,
    )
    return page


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = create_consolidated_preview_app(scenario_root, output_root)
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != "/"]

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_preview_page_for_test())

    install_gravity_model_routes(app, scenario_root)
    return app
