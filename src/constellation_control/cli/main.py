from pathlib import Path

import typer

from constellation_control.application.run import run_scenario

app = typer.Typer(help="Constellation Control CLI")


@app.command()
def run(scenario: Path, output: Path = Path("runs")) -> None:
    """Run one validated YAML scenario and write reproducible artifacts."""
    run_dir = run_scenario(scenario, output)
    typer.echo(run_dir)


if __name__ == "__main__":
    app()
