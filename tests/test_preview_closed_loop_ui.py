from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from constellation_control.preview.http_app import (
    PREVIEW_VERSION,
    _CLOSED_LOOP_CARD,
    create_preview_app,
    render_preview_page_for_test,
)


def _repo_root() -> Path:
    return Path(__file__).parents[1]


def test_composed_preview_reports_release_0_1_5(tmp_path: Path) -> None:
    app = create_preview_app(_repo_root() / "scenarios", tmp_path)
    client = TestClient(app)
    assert PREVIEW_VERSION == "0.1.5"
    assert app.version == "0.1.5"
    assert client.get("/health").json() == {"status": "ok", "preview": "0.1.5"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Engineering Preview 0.1.5" in page.text


def test_closed_loop_page_is_bilingual_and_exposes_explicit_p2_contract() -> None:
    page = render_preview_page_for_test()
    assert "Замкнутый контур управления / Closed-loop control" in page
    assert "Политика / Policy" in page
    assert "NO CONTROL" in page
    assert "RETURN-TO-CENTER" in page
    assert "BOUNDARY-TO-BOUNDARY" in page
    assert "Явный control profile JSON / Explicit control profile JSON" in page
    assert "Введите явный control profile JSON / Supply an explicit control profile JSON." in page
    assert "Результат / Result" in page
    assert "Projected years to reserve / Лет до резерва" in page
    assert "Authority backend(s)" in page
    assert "Force fingerprint" in page
    assert "frame" in page and "time scale" in page
    assert "Δu = M+ω" in page


def test_closed_loop_card_contains_no_numerical_control_defaults() -> None:
    # The P2 operator card may name required fields but must not prefill any numerical control value.
    required_fields = (
        "campaign_horizon_s",
        "coast_horizon_s",
        "coast_output_step_s",
        "max_corrections",
        "authority_times_s",
        "maneuver_windows",
        "max_abs_impulse_rtn_m_s",
        "min_impulse_bit_m_s",
        "trust_tolerances_roe",
        "target_roe",
        "w_tracking",
        "w_max",
    )
    for field in required_fields:
        assert field in _CLOSED_LOOP_CARD
    assert "No control values are prefilled by Preview" in _CLOSED_LOOP_CARD
    assert not re.search(r'value=["\']\s*[-+]?\d', _CLOSED_LOOP_CARD)
    assert "0.001" not in _CLOSED_LOOP_CARD
    assert "0.2" not in _CLOSED_LOOP_CARD
    assert "1e-" not in _CLOSED_LOOP_CARD.lower()


def test_closed_loop_context_is_derived_from_selected_scenario_not_ui_constants() -> None:
    page = render_preview_page_for_test()
    assert "current.normalized.constraints" in page
    assert "c.phase_corridor_rad" in page
    assert "c.min_pair_distance_m" in page
    assert "c.propellant_reserve_fraction" in page
    assert "current.force_model_fingerprint" in page
    assert "current.frame" in page
    assert "current.time_scale" in page
