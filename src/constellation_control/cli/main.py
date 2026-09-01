from pathlib import Path
from typing import Annotated

import typer

from constellation_control.application.design_pipeline import run_design_application
from constellation_control.application.robustness import run_robustness_application
from constellation_control.application.run import run_scenario

app = typer.Typer(help="Constellation Control CLI", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Constellation Control command group."""


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(help="Validated YAML scenario")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Root directory for reproducible run artifacts"),
    ] = None,
) -> None:
    """Run one validated YAML scenario and write reproducible artifacts."""
    output_root = output if output is not None else Path("runs")
    run_dir = run_scenario(scenario, output_root)
    typer.echo(run_dir)


@app.command()
def design(
    screening: Annotated[Path, typer.Argument(help="Screening YAML scenario")],
    validation: Annotated[Path, typer.Argument(help="Numerical Orekit validation YAML scenario")],
    pipeline: Annotated[Path, typer.Argument(help="Design pipeline YAML configuration")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Root directory for design evidence artifacts"),
    ] = None,
) -> None:
    """Search, rank and numerically validate constellation design candidates."""
    output_root = output if output is not None else Path("runs")
    run_dir = run_design_application(screening, validation, pipeline, output_root)
    typer.echo(run_dir)


@app.command()
def robustness(
    scenario: Annotated[Path, typer.Argument(help="Numerical Orekit validation YAML scenario")],
    campaign: Annotated[Path, typer.Argument(help="Robustness campaign YAML configuration")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Root directory for robustness evidence artifacts"),
    ] = None,
) -> None:
    """Run a resumable high-fidelity robustness campaign for an accepted candidate."""
    output_root = output if output is not None else Path("runs")
    run_dir = run_robustness_application(scenario, campaign, output_root)
    typer.echo(run_dir)


@app.command()
def preview(
    scenarios: Annotated[
        Path,
        typer.Option("--scenarios", help="Directory containing expert YAML scenarios"),
    ] = Path("scenarios"),
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Root directory for preview run artifacts"),
    ] = Path("runs"),
    host: Annotated[
        str,
        typer.Option("--host", help="Preview bind address; localhost is the safe default"),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Preview HTTP port")] = 8765,
) -> None:
    """Start the local Engineering Preview web shell."""
    try:
        import uvicorn

        from constellation_control.preview.gravity_release_app import create_preview_app
    except ImportError as exc:
        missing = getattr(exc, "name", None) or str(exc)
        raise typer.BadParameter(
            f"Preview dependency/import is missing: {missing}; install with .[preview]"
        ) from exc

    application = create_preview_app(scenarios, output)
    typer.echo(f"Engineering Preview: http://{host}:{port}")
    uvicorn.run(application, host=host, port=port)


if __name__ == "__main__":
    app()
