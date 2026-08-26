from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("relative operations numeric field has invalid type")
    return float(value)


def preview_operations_payload(run_dir: Path) -> dict[str, object]:
    """Read persisted run authority and project it into the Preview operator surface.

    No orbital quantity is recomputed here. The Preview consumes the `summary.json`
    produced by `run_scenario`, keeping reporting and UI on one physical authority.
    """

    summary_path = run_dir / "summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary.json must contain an object")
    raw_pairs = payload.get("relative_operations", [])
    if not isinstance(raw_pairs, list):
        raise ValueError("summary relative_operations must be a list")

    pairs: list[dict[str, object]] = []
    for raw in raw_pairs:
        if not isinstance(raw, dict):
            raise ValueError("relative_operations entries must be objects")
        item = cast(dict[str, Any], raw)
        corridor = item.get("phase_corridor")
        if not isinstance(corridor, dict):
            raise ValueError("relative operations entry is missing phase_corridor")
        corridor_map = cast(dict[str, Any], corridor)
        inside = corridor_map.get("inside_corridor")
        if not isinstance(inside, bool):
            raise ValueError("phase corridor status must be boolean")

        final_delta_u_deg = _as_float(item.get("final_delta_u_deg"))
        drift_deg_day = _as_float(item.get("secular_delta_u_rate_deg_day"))
        drift_deg_year = _as_float(item.get("secular_delta_u_rate_deg_julian_year"))
        final_along_track_m = _as_float(item.get("final_along_track_proxy_m"))
        along_track_rate_m_s = _as_float(item.get("secular_along_track_proxy_rate_m_s"))
        half_width_deg = _as_float(corridor_map.get("half_width_deg"))
        boundary_deg = _as_float(corridor_map.get("predicted_boundary_deg"))
        time_days = _as_float(corridor_map.get("time_to_boundary_days"))

        pairs.append(
            {
                "pair_id": str(item.get("pair_id", "")),
                "reference_id": str(item.get("reference_id", "")),
                "deputy_id": str(item.get("deputy_id", "")),
                "final_delta_u_deg": final_delta_u_deg,
                "drift_deg_day": drift_deg_day,
                "drift_deg_julian_year": drift_deg_year,
                "final_along_track_proxy_km": (
                    None if final_along_track_m is None else final_along_track_m / 1000.0
                ),
                "along_track_proxy_rate_m_s": along_track_rate_m_s,
                "corridor_half_width_deg": half_width_deg,
                "inside_corridor": inside,
                "predicted_boundary_deg": boundary_deg,
                "time_to_boundary_days": time_days,
                "phase_semantics": str(item.get("phase_semantics", "")),
                "along_track_semantics": str(item.get("along_track_semantics", "")),
                "corridor_semantics": str(item.get("phase_corridor_semantics", "")),
            }
        )

    return {
        "pairs": pairs,
        "available": bool(pairs),
        "source": "summary.json:relative_operations",
    }
