from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from constellation_control.adapters.orekit.adapter import orekit_progress_callback
from constellation_control.application.run import run_scenario


def _write_stage(
    source: Path,
    target: Path,
    duration_s: float,
    satellite_id: str | None,
    output_step_s: float | None,
) -> None:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["duration_s"] = duration_s
    if output_step_s is not None:
        payload["output_step_s"] = output_step_s
    if satellite_id is not None:
        satellites = payload["constellation"]["satellites"]
        selected = [sat for sat in satellites if sat.get("satellite_id") == satellite_id]
        if len(selected) != 1:
            raise ValueError(f"expected exactly one satellite_id={satellite_id}, found {len(selected)}")
        selected[0].pop("reference_id", None)
        payload["constellation"]["satellites"] = selected
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output-step", type=float)
    parser.add_argument("--satellite")
    args = parser.parse_args()

    args.work.mkdir(parents=True, exist_ok=True)
    suffix = f"-{args.satellite}" if args.satellite else "-full"
    scenario = args.work / f"scenario-{int(args.duration)}s{suffix}.yaml"
    _write_stage(args.source, scenario, args.duration, args.satellite, args.output_step)

    last: dict[str, object] = {}

    def progress(snapshot: dict[str, object]) -> None:
        nonlocal last
        last = dict(snapshot)
        if snapshot.get("error") is not None or snapshot.get("phase") == "osculating_to_mean":
            print("PROGRESS " + json.dumps(snapshot, ensure_ascii=False, sort_keys=True), flush=True)

    try:
        with orekit_progress_callback(progress):
            run_dir = run_scenario(scenario, args.work / "runs")
        print(
            f"RESULT success duration_s={args.duration:g} output_step_s={args.output_step or 'source'} "
            f"satellite={args.satellite or 'ALL'} run_dir={run_dir}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"RESULT failure duration_s={args.duration:g} output_step_s={args.output_step or 'source'} "
            f"satellite={args.satellite or 'ALL'} exception={type(exc).__name__}: {exc}",
            flush=True,
        )
        print("LAST_PROGRESS " + json.dumps(last, ensure_ascii=False, sort_keys=True), flush=True)
        raise


if __name__ == "__main__":
    main()
