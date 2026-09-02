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
from constellation_control.preview.operator_tabs import (
    OPERATOR_TABS_CARD,
    OPERATOR_TABS_SCRIPT,
    OPERATOR_TABS_STYLE,
)

PREVIEW_VERSION = "0.2.6"


def render_preview_page_for_test() -> str:
    page = render_consolidated_page().replace("Engineering Preview 0.2.5", f"Engineering Preview {PREVIEW_VERSION}")
    page = page.replace("</head>", f"{OPERATOR_TABS_STYLE}</head>", 1)
    page = page.replace("<section>", f"<section>{OPERATOR_TABS_CARD}", 1)
    page = page.replace("</section></main>", f"{GRAVITY_MODEL_CARD}</section></main>", 1)
    page = page.replace(
        "bootstrap().catch(e=>setStatus(String(e),'danger'));",
        f"{GRAVITY_MODEL_SCRIPT}\n"
        "const gravityBootstrap=bootstrap;"
        "bootstrap=async function(){await gravityBootstrap();if(typeof syncGravityModel==='function')syncGravityModel();};\n"
        f"{OPERATOR_TABS_SCRIPT}\n"
        "bootstrap().catch(e=>setStatus(String(e),'danger'));",
        1,
    )
    return page


def create_preview_app(scenario_root: Path = Path("scenarios"), output_root: Path = Path("runs")) -> FastAPI:
    app = create_consolidated_preview_app(scenario_root, output_root)
    app.version = PREVIEW_VERSION
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) not in {"/", "/health"}
    ]

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(render_preview_page_for_test())

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "preview": PREVIEW_VERSION}

    install_gravity_model_routes(app, scenario_root)
    return app
