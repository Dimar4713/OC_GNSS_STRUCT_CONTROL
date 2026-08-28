from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import constellation_control.preview.release_app as release_app


def _repo_root() -> Path:
    return Path(__file__).parents[1]


class Dump:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, **_: object) -> dict[str, object]:
        return self.payload


def test_release_page_is_020_bilingual_and_has_no_numeric_defaults(tmp_path: Path) -> None:
    client = TestClient(release_app.create_preview_app(_repo_root() / "scenarios", tmp_path))
    assert client.get("/health").json() == {"status": "ok", "preview": "0.2.0"}
    page = client.get("/").text
    assert "Engineering Preview 0.2.0" in page
    assert "Optimal Operations Workspace 0.2" in page
    assert "Рабочее место оптимальных операций" in page
    assert "DSST DESIGN = screening only" in page
    assert 'id="optimalProfile"' in page
    assert 'id="optimalDecisionPolicy"' in page
    assert 'id="optimalHybridStep"' in page
    assert 'id="optimalBracketPadding"' in page
    assert 'value="0.05"' not in page
    assert 'value="0.5"' not in page
    assert "No risk thresholds are prefilled" in page


def test_release_foundation_endpoint_delegates_and_returns_persisted_identity(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "study-a" / "foundation-abc"
    run_dir.mkdir(parents=True)
    for name in release_app._OPTIMAL_FOUNDATION_ARTIFACTS:
        (run_dir / name).write_text("{}", encoding="utf-8")
    candidate = Dump({"candidate_id": "c1", "trigger_fraction": 0.4, "target_fraction": 0.2, "feasible": True})
    preflight = Dump({"study_id": "study-a", "scenario_config_hash": "a" * 64, "identity": {}})
    baseline = SimpleNamespace(strategy=Dump({"strategy_id": "baseline-no-control"}))
    fake = SimpleNamespace(
        foundation=SimpleNamespace(
            preflight=preflight,
            baselines=(baseline,),
            screening=SimpleNamespace(candidates=(candidate,), pareto_candidate_ids=("c1",)),
        ),
        artifacts=SimpleNamespace(run_dir=str(run_dir)),
        release_inputs_sha256="b" * 64,
    )
    calls: list[dict[str, object]] = []

    def run(*args: object, **kwargs: object):
        calls.append(kwargs)
        return fake

    monkeypatch.setattr(release_app, "run_preview_optimal_operations_foundation_release", run)
    client = TestClient(release_app.create_preview_app(_repo_root() / "scenarios", tmp_path))
    profile = {
        "study_id": "x",
        "scenario_name": "orekit_validation_smoke.yaml",
    }
    response = client.post(
        "/api/optimal-operations/foundation-runs",
        json={
            "design_scenario_name": "orekit_design_smoke.yaml",
            "validation_scenario_name": "orekit_validation_smoke.yaml",
            "profile": profile,
        },
    )
    # Pydantic must reject an incomplete profile before any release execution.
    assert response.status_code == 422
    assert calls == []


def test_release_decision_requires_explicit_hybrid_numbers_and_policy(tmp_path: Path) -> None:
    client = TestClient(release_app.create_preview_app(_repo_root() / "scenarios", tmp_path))
    response = client.post(
        "/api/optimal-operations/decision-runs",
        json={
            "foundation_group": "study-a",
            "foundation_run_id": "foundation-abc",
            "candidate_id": "c1",
            "robustness_config_name": "robustness_campaign_smoke.yaml",
            "decision_policy": {
                "recommendation_strategy_id": "optimized-c1",
                "robustness_required": True,
                "violation_probability_limits": {},
                "violation_probability_objectives": [],
            },
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    text = str(detail)
    assert "hybrid_validation_output_step_s" in text
    assert "screening_bracket_padding_steps" in text


def test_release_artifact_route_is_allowlisted(tmp_path: Path) -> None:
    run_dir = tmp_path / "study-a" / "decision-abc"
    run_dir.mkdir(parents=True)
    (run_dir / "operational_decision.json").write_text("{}", encoding="utf-8")
    (run_dir / "secret.txt").write_text("no", encoding="utf-8")
    client = TestClient(release_app.create_preview_app(_repo_root() / "scenarios", tmp_path))
    assert client.get("/api/optimal-operations-results/study-a/decision-abc/operational_decision.json").status_code == 200
    assert client.get("/api/optimal-operations-results/study-a/decision-abc/secret.txt").status_code == 404
