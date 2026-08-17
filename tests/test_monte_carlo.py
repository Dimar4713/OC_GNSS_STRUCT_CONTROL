from constellation_control.domain.models import MonteCarloConfig
from constellation_control.uncertainty.monte_carlo import run_monte_carlo


def evaluate(sample: dict[str, float | int]) -> dict[str, object]:
    x = float(sample["x"])
    return {"delta_v_total_m_s": abs(x), "violations": {"phase": abs(x) > 1.0}}


def test_monte_carlo_is_deterministic_for_fixed_seed() -> None:
    config = MonteCarloConfig(samples=50, workers=4, seed=1234, perturbation_sigmas={"x": 2.0})
    first = run_monte_carlo(config, evaluate)
    second = run_monte_carlo(config, evaluate)
    assert first.samples == second.samples
    assert first.outcomes == second.outcomes
    assert first.summary == second.summary
    assert "delta_v_total_m_s" in first.summary["statistics"]
