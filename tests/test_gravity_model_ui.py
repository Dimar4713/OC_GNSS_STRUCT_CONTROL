import pytest
from pydantic import ValidationError

from constellation_control.preview.gravity_model_ui import GravityModelCreateRequest, gravity_model_label
from constellation_control.preview.gravity_release_app import render_preview_page_for_test


def request(degree: int, order: int) -> GravityModelCreateRequest:
    return GravityModelCreateRequest(
        source_scenario_name="source.yaml",
        target_scenario_name="target.yaml",
        new_scenario_id="target",
        gravity_degree=degree,
        gravity_order=order,
    )


def test_gravity_range_accepts_kepler_j2_and_32x32() -> None:
    assert (request(0, 0).gravity_degree, request(0, 0).gravity_order) == (0, 0)
    assert gravity_model_label(0, 0) == "KEPLER"
    assert gravity_model_label(2, 0) == "J2 / EIGEN-6S 2x0"
    assert gravity_model_label(32, 32) == "EIGEN-6S 32x32"


def test_gravity_range_fails_closed_above_32_or_order_above_degree() -> None:
    with pytest.raises(ValidationError):
        request(33, 33)
    with pytest.raises(ValidationError):
        request(8, 9)
    with pytest.raises(ValidationError):
        request(0, 1)


def test_gravity_controls_are_exposed_in_preview_html() -> None:
    page = render_preview_page_for_test()
    assert 'id="gravityModelCard"' in page
    assert "Kepler 0x0" in page
    assert "J2 / 2x0" in page
    assert "EIGEN-6S 32x32" in page
    assert "/api/gravity-model/create" in page
