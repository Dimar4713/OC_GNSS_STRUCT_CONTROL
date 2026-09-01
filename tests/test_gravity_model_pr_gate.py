from constellation_control.preview.gravity_model_ui import gravity_model_label


def test_gravity_model_pr_gate_marker() -> None:
    assert gravity_model_label(8, 8) == "EIGEN-6S 8x8"
