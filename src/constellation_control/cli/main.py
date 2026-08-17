from pathlib import Path
from typing import Annotated

import typer

from constellation_control.application.run import run_scenario

app = typer.Typer(help="Constellation Control CLI")


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(help="Validated YAML scenario")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Root directory for reproducible run artifacts"),
    ] = Path("runs"),
) -> None:
    """Run one validated YAML scenario and write reproducible artifacts."""
    run_dir = run_scenario(scenario, output)
    typer.echo(run_dir)


if __name__ == "__main__":
    app()
