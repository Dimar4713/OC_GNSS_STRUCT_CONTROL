import json
from pathlib import Path

import pytest

from constellation_control.preview.operations import preview_operations_payload


def test_preview_operations_payload_projects_persisted_summary_without_recomputing(tmp_path: Path) -> None:
    summary = {
        "relative_operations": [
            {
                "pair_id": "ADD-01/REF-01",
                "reference_id": "REF-01",
                "deputy_id": "ADD-01",
                "final_delta_u_deg": 2.5,
                "secular_delta_u_rate_deg_day": 0.25,
                "secular_delta_u_rate_deg_julian_year": 91.3125,
                "final_along_track_proxy_m": 12345.0,
                "secular_along_track_proxy_rate_m_s": 0.0123,
                "phase_semantics": "mean phase M+omega; not osculating argument of latitude",
                "along_track_semantics": "near-circular mean arc proxy; not Cartesian separation",
                "phase_corridor_semantics": "configured symmetric corridor",
                "phase_corridor": {
                    "half_width_deg": 5.0,
                    "inside_corridor": True,
                    "predicted_boundary_deg": 5.0,
                    "time_to_boundary_days": 10.0,
                },
            }
        ]
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    payload = preview_operations_payload(tmp_path)

    assert payload["available"] is True
    assert payload["source"] == "summary.json:relative_operations"
    pair = payload["pairs"][0]
    assert pair["pair_id"] == "ADD-01/REF-01"
    assert pair["final_delta_u_deg"] == pytest.approx(2.5)
    assert pair["drift_deg_day"] == pytest.approx(0.25)
    assert pair["drift_deg_julian_year"] == pytest.approx(91.3125)
    assert pair["final_along_track_proxy_km"] == pytest.approx(12.345)
    assert pair["along_track_proxy_rate_m_s"] == pytest.approx(0.0123)
    assert pair["corridor_half_width_deg"] == pytest.approx(5.0)
    assert pair["inside_corridor"] is True
    assert pair["predicted_boundary_deg"] == pytest.approx(5.0)
    assert pair["time_to_boundary_days"] == pytest.approx(10.0)


def test_preview_operations_payload_preserves_unavailable_crossing_time(tmp_path: Path) -> None:
    summary = {
        "relative_operations": [
            {
                "pair_id": "ADD-01/REF-01",
                "reference_id": "REF-01",
                "deputy_id": "ADD-01",
                "final_delta_u_deg": 1.0,
                "secular_delta_u_rate_deg_day": 0.0,
                "secular_delta_u_rate_deg_julian_year": 0.0,
                "final_along_track_proxy_m": 1000.0,
                "secular_along_track_proxy_rate_m_s": 0.0,
                "phase_semantics": "mean phase",
                "along_track_semantics": "proxy",
                "phase_corridor_semantics": "configured corridor",
                "phase_corridor": {
                    "half_width_deg": 5.0,
                    "inside_corridor": True,
                    "predicted_boundary_deg": None,
                    "time_to_boundary_days": None,
                },
            }
        ]
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    pair = preview_operations_payload(tmp_path)["pairs"][0]

    assert pair["predicted_boundary_deg"] is None
    assert pair["time_to_boundary_days"] is None


def test_preview_operations_payload_allows_run_without_reference_pairs(tmp_path: Path) -> None:
    (tmp_path / "summary.json").write_text(
        json.dumps({"relative_operations": []}),
        encoding="utf-8",
    )

    assert preview_operations_payload(tmp_path) == {
        "pairs": [],
        "available": False,
        "source": "summary.json:relative_operations",
    }
