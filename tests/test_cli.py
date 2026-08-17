from pathlib import Path

from typer.testing import CliRunner

from constellation_control.cli.main import app


runner = CliRunner()


def test_run_accepts_output_option(monkeypatch) -> None:
    captured: dict[str, Path] = {}

    def fake_run_scenario(scenario: Path, output: Path) -> Path:
        captured["scenario"] = scenario
        captured["output"] = output
        return output / "scenario" / "run-id"

    monkeypatch.setattr("constellation_control.cli.main.run_scenario", fake_run_scenario)
    result = runner.invoke(app, ["run", "scenario.yaml", "--output", "evidence"])

    assert result.exit_code == 0, result.output
    assert captured == {"scenario": Path("scenario.yaml"), "output": Path("evidence")}
    assert "evidence/scenario/run-id" in result.output.replace("\\", "/")


def test_run_accepts_short_output_option(monkeypatch) -> None:
    monkeypatch.setattr(
        "constellation_control.cli.main.run_scenario",
        lambda scenario, output: output / "ok",
    )
    result = runner.invoke(app, ["run", "scenario.yaml", "-o", "runs"])
    assert result.exit_code == 0, result.output
