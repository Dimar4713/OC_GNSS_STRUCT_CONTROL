from __future__ import annotations

import html
import json
from collections.abc import Mapping
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px

from constellation_control.domain.models import ExperimentRunManifest


def _save_line(frame: pd.DataFrame, x: str, ys: list[str], title: str, path: Path) -> None:
    present = [column for column in ys if column in frame]
    if not present or x not in frame:
        return
    figure, axis = plt.subplots()
    for column in present:
        axis.plot(frame[x], frame[column], label=column)
    axis.set_title(title)
    axis.set_xlabel(x)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def generate_engineering_plots(timeseries: pd.DataFrame, output_dir: Path) -> None:
    _save_line(timeseries, "time_s", ["delta_lambda_rad", "trend_rad", "harmonic_rad"], "Relative phase", output_dir / "01_delta_lambda.png")
    _save_line(timeseries, "time_s", ["delta_a_mean_m"], "Mean semi-major-axis difference", output_dir / "02_delta_a_mean.png")
    _save_line(timeseries, "time_s", ["delta_ex", "delta_ey"], "Relative eccentricity vector", output_dir / "03_eccentricity_vector.png")
    _save_line(timeseries, "time_s", ["delta_ix", "delta_iy"], "Relative inclination vector", output_dir / "04_inclination_vector.png")
    _save_line(timeseries, "time_s", ["pair_distance_m"], "Pair distance history", output_dir / "05_minimum_distance.png")
    if {"time_s", "delta_lambda_rad"}.issubset(timeseries.columns):
        figure = px.line(timeseries, x="time_s", y="delta_lambda_rad", color="pair_id", title="Interactive relative phase")
        figure.write_html(output_dir / "interactive_delta_lambda.html", include_plotlyjs="cdn")


def write_run_artifacts(
    output_dir: Path,
    manifest: ExperimentRunManifest,
    summary: Mapping[str, object],
    timeseries: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    timeseries.to_csv(output_dir / "timeseries.csv", index=False)
    timeseries.to_parquet(output_dir / "timeseries.parquet", index=False)
    generate_engineering_plots(timeseries, output_dir)

    md = [
        f"# Constellation Control run {manifest.run_id}",
        "",
        f"- Scenario: `{manifest.scenario_id}`",
        f"- Backend: `{manifest.backend}` `{manifest.backend_version}`",
        f"- Force mode: `{manifest.force_model_mode}`",
        f"- Force-model fingerprint: `{manifest.force_model_fingerprint}`",
        f"- Config hash: `{manifest.config_hash}`",
        f"- Epoch: `{manifest.epoch.isoformat()}`",
        f"- Random seed: `{manifest.random_seed}`",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2, sort_keys=True),
        "```",
    ]
    markdown = "\n".join(md) + "\n"
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    (output_dir / "report.html").write_text(f"<html><body><pre>{html.escape(markdown)}</pre></body></html>", encoding="utf-8")
