from __future__ import annotations

import html
import json
from collections.abc import Mapping
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd
import plotly.express as px

from constellation_control.domain.models import ExperimentRunManifest


def _save_line(
    frame: pd.DataFrame,
    x: str,
    ys: list[str],
    title: str,
    path: Path,
    *,
    group: str | None = None,
) -> None:
    present = [column for column in ys if column in frame]
    if not present or x not in frame or frame.empty:
        return
    figure, axis = plt.subplots()
    if group and group in frame:
        for group_id, group_frame in frame.groupby(group, sort=True):
            for column in present:
                axis.plot(group_frame[x], group_frame[column], label=f"{group_id}:{column}")
    else:
        for column in present:
            axis.plot(frame[x], frame[column], label=column)
    axis.set_title(title)
    axis.set_xlabel(x)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def _save_ground_track(frame: pd.DataFrame, path: Path) -> None:
    required = {"satellite_id", "longitude_rad", "geocentric_latitude_rad"}
    if frame.empty or not required.issubset(frame.columns):
        return
    figure, axis = plt.subplots()
    for satellite_id, satellite_frame in frame.groupby("satellite_id", sort=True):
        axis.plot(
            satellite_frame["longitude_rad"],
            satellite_frame["geocentric_latitude_rad"],
            label=str(satellite_id),
        )
    axis.set_title("Earth-fixed ground track (geocentric)")
    axis.set_xlabel("longitude_rad")
    axis.set_ylabel("geocentric_latitude_rad")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def _save_navigation_geometry(frame: pd.DataFrame, path: Path) -> None:
    required = {"site_id", "time_s", "visible_count", "pdop"}
    if frame.empty or not required.issubset(frame.columns):
        return
    figure, axis = plt.subplots()
    plotted_pdop = False
    for site_id, site_frame in frame.groupby("site_id", sort=True):
        finite = site_frame[site_frame["pdop"].notna()]
        if not finite.empty:
            axis.plot(finite["time_s"], finite["pdop"], label=f"{site_id}:PDOP")
            plotted_pdop = True
    axis.set_title("Navigation geometry / PDOP")
    axis.set_xlabel("time_s")
    axis.set_ylabel("PDOP")
    if plotted_pdop:
        axis.legend()
    else:
        axis.text(
            0.5,
            0.5,
            "PDOP unavailable for configured geometry",
            horizontalalignment="center",
            verticalalignment="center",
            transform=axis.transAxes,
        )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def generate_engineering_plots(
    timeseries: pd.DataFrame,
    output_dir: Path,
    *,
    ground_track: pd.DataFrame | None = None,
    navigation_geometry: pd.DataFrame | None = None,
    resources: pd.DataFrame | None = None,
) -> None:
    _save_line(
        timeseries,
        "time_s",
        ["delta_lambda_rad", "trend_rad", "harmonic_rad"],
        "D'Amico relative longitude coordinate",
        output_dir / "01_delta_lambda.png",
        group="pair_id",
    )
    _save_line(
        timeseries,
        "time_s",
        ["delta_a_mean_m"],
        "Mean semi-major-axis difference",
        output_dir / "02_delta_a_mean.png",
        group="pair_id",
    )
    _save_line(
        timeseries,
        "time_s",
        ["delta_ex", "delta_ey"],
        "Relative eccentricity vector",
        output_dir / "03_eccentricity_vector.png",
        group="pair_id",
    )
    _save_line(
        timeseries,
        "time_s",
        ["delta_ix", "delta_iy"],
        "Relative inclination vector",
        output_dir / "04_inclination_vector.png",
        group="pair_id",
    )
    _save_line(
        timeseries,
        "time_s",
        ["pair_distance_m"],
        "Pair distance history",
        output_dir / "05_minimum_distance.png",
        group="pair_id",
    )
    _save_line(
        timeseries,
        "time_s",
        ["delta_raan_rad"],
        "Relative RAAN",
        output_dir / "06_delta_raan.png",
        group="pair_id",
    )
    if ground_track is not None:
        _save_ground_track(ground_track, output_dir / "07_ground_track.png")
    if navigation_geometry is not None:
        _save_navigation_geometry(navigation_geometry, output_dir / "08_navigation_pdop.png")
    if resources is not None:
        _save_line(
            resources,
            "time_s",
            ["cumulative_delta_v_m_s"],
            "Maneuver cumulative delta-V",
            output_dir / "09_maneuver_delta_v.png",
            group="satellite_id",
        )
        _save_line(
            resources,
            "time_s",
            ["residual_propellant_kg", "required_reserve_kg"],
            "Propellant and reserve",
            output_dir / "10_propellant_reserve.png",
            group="satellite_id",
        )
    _save_line(
        timeseries,
        "time_s",
        ["delta_u_mean_deg", "phase_corridor_upper_deg", "phase_corridor_lower_deg"],
        "Operator mean phase difference Delta u and configured corridor",
        output_dir / "11_delta_u_mean.png",
        group="pair_id",
    )
    _save_line(
        timeseries,
        "time_s",
        ["along_track_mean_arc_proxy_m"],
        "Mean along-track arc proxy a_ref * Delta u",
        output_dir / "12_along_track_mean_arc_proxy.png",
        group="pair_id",
    )
    if {"time_s", "delta_lambda_rad", "pair_id"}.issubset(timeseries.columns):
        figure = px.line(
            timeseries,
            x="time_s",
            y="delta_lambda_rad",
            color="pair_id",
            title="Interactive D'Amico relative longitude coordinate",
        )
        figure.write_html(output_dir / "interactive_delta_lambda.html", include_plotlyjs="cdn")
    if {"time_s", "delta_u_mean_deg", "pair_id"}.issubset(timeseries.columns):
        figure = px.line(
            timeseries,
            x="time_s",
            y="delta_u_mean_deg",
            color="pair_id",
            title="Interactive operator mean phase difference Delta u",
        )
        figure.write_html(output_dir / "interactive_delta_u_mean.html", include_plotlyjs="cdn")


def _write_optional_table(output_dir: Path, name: str, frame: pd.DataFrame | None) -> None:
    if frame is None:
        return
    frame.to_csv(output_dir / f"{name}.csv", index=False)
    frame.to_parquet(output_dir / f"{name}.parquet", index=False)
    frame.to_json(output_dir / f"{name}.json", orient="records", indent=2)


def write_run_artifacts(
    output_dir: Path,
    manifest: ExperimentRunManifest,
    summary: Mapping[str, object],
    timeseries: pd.DataFrame,
    *,
    ground_track: pd.DataFrame | None = None,
    navigation_geometry: pd.DataFrame | None = None,
    resources: pd.DataFrame | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    timeseries.to_csv(output_dir / "timeseries.csv", index=False)
    timeseries.to_parquet(output_dir / "timeseries.parquet", index=False)
    _write_optional_table(output_dir, "ground_track", ground_track)
    _write_optional_table(output_dir, "navigation_geometry", navigation_geometry)
    _write_optional_table(output_dir, "resources", resources)
    generate_engineering_plots(
        timeseries,
        output_dir,
        ground_track=ground_track,
        navigation_geometry=navigation_geometry,
        resources=resources,
    )

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
    (output_dir / "report.html").write_text(
        f"<html><body><pre>{html.escape(markdown)}</pre></body></html>",
        encoding="utf-8",
    )
