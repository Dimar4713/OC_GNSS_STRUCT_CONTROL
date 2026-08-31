from __future__ import annotations

from pathlib import Path

import pytest

import constellation_control.application.run as run_module
from constellation_control.application.run import load_scenario


class _StopAfterCapture(RuntimeError):
    pass


def test_run_scenario_fails_resource_preflight_before_propagator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    constructed = False

    class FakePropagator:
        def __init__(self) -> None:
            nonlocal constructed
            constructed = True

        def propagate(self, request):  # noqa: ANN001, ANN201
            raise AssertionError("propagator must not run when resource preflight fails")

    def fail_preflight(scenario):  # noqa: ANN001, ANN201
        raise ValueError("preflight-sentinel")

    monkeypatch.setattr(run_module, "build_maneuver_resource_rows", fail_preflight)
    monkeypatch.setattr(run_module, "SyntheticMeanPropagator", FakePropagator)

    with pytest.raises(ValueError, match="preflight-sentinel"):
        run_module.run_scenario(Path("scenarios/mvp_45deg.yaml"), tmp_path)

    assert not constructed


def test_run_scenario_passes_operational_satellites_to_propagation_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = load_scenario(Path("scenarios/mvp_45deg.yaml"))
    first = source.constellation.satellites[0]
    operational_first = first.model_copy(
        update={
            "spacecraft": first.spacecraft.model_copy(
                update={
                    "dry_mass_kg": first.spacecraft.dry_mass_kg - 5.0,
                    "propellant_mass_kg": 5.0,
                    "isp_s": first.spacecraft.isp_s + 17.0,
                }
            )
        }
    )
    operational = (operational_first, *source.constellation.satellites[1:])
    captured = {}

    monkeypatch.setattr(run_module, "build_maneuver_resource_rows", lambda scenario: [])
    monkeypatch.setattr(run_module, "resolve_operational_satellites", lambda scenario: operational)

    class CapturePropagator:
        def propagate(self, request):  # noqa: ANN001, ANN201
            captured["request"] = request
            raise _StopAfterCapture("captured")

    monkeypatch.setattr(run_module, "SyntheticMeanPropagator", CapturePropagator)

    with pytest.raises(_StopAfterCapture, match="captured"):
        run_module.run_scenario(Path("scenarios/mvp_45deg.yaml"), tmp_path)

    request = captured["request"]
    assert request.satellites[0].spacecraft.initial_mass_kg == pytest.approx(
        operational_first.spacecraft.initial_mass_kg
    )
    assert request.satellites[0].spacecraft.propellant_mass_kg == pytest.approx(5.0)
    assert request.satellites[0].spacecraft.isp_s == pytest.approx(first.spacecraft.isp_s + 17.0)
