from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from constellation_control.adapters.orekit.adapter import orekit_progress_callback
from constellation_control.application.run import run_scenario


def _write_stage(source: Path, target: Path, duration_s: float) -> None:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["duration_s"] = duration_s
    target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--duration", type=float, required=True)
    args = parser.parse_args()

    args.work.mkdir(parents=True, exist_ok=True)
    scenario = args.work / f"scenario-{int(args.duration)}s.yaml"
    _write_stage(args.source, scenario, args.duration)

    last: dict[str, object] = {}

    def progress(snapshot: dict[str, object]) -> None:
        nonlocal last
        last = dict(snapshot)
        if snapshot.get("error") is not None or snapshot.get("phase") == "osculating_to_mean":
            print("PROGRESS " + json.dumps(snapshot, ensure_ascii=False, sort_keys=True), flush=True)

    try:
        with orekit_progress_callback(progress):
            run_dir = run_scenario(scenario, args.work / "runs")
        print(f"RESULT success duration_s={args.duration:g} run_dir={run_dir}", flush=True)
    except Exception as exc:
        print(f"RESULT failure duration_s={args.duration:g} exception={type(exc).__name__}: {exc}", flush=True)
        print("LAST_PROGRESS " + json.dumps(last, ensure_ascii=False, sort_keys=True), flush=True)
        raise


if __name__ == "__main__":
    main()
