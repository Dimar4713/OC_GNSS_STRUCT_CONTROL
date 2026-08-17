from pathlib import Path

from fastapi import FastAPI

from constellation_control.application.run import run_scenario

app = FastAPI(title="Constellation Control", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/runs")
def create_run(scenario_path: str, output_root: str = "runs") -> dict[str, str]:
    run_dir = run_scenario(Path(scenario_path), Path(output_root))
    return {"run_dir": str(run_dir)}
