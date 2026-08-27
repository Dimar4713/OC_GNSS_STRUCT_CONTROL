from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.optimization.operational_robustness import (
    StrategyRealizationOutcome,
    StrategyRobustnessEvidence,
    RealizationStatus,
    common_sample_set_from_generated,
)
from constellation_control.uncertainty.campaign import (
    RobustnessCampaignConfig,
    generate_campaign_samples,
)


class CompletedOperationalRealization(BaseModel):
    """Normalized authoritative result returned by one strategy executor."""

    model_config = ConfigDict(frozen=True)

    realization: int = Field(ge=0)
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, float]
    violations: dict[str, bool]
    authority_backend: str = Field(min_length=1)
    authority_force_model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_metrics(self) -> CompletedOperationalRealization:
        if any(not np.isfinite(value) for value in self.metrics.values()):
            raise ValueError("completed operational robustness metrics must be finite")
        return self


StrategySampleExecutor = Callable[[Mapping[str, object]], CompletedOperationalRealization | None]
SampleGenerator = Callable[[RobustnessCampaignConfig], tuple[dict[str, object], ...]]


class OperationalRobustnessStudyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategies: tuple[StrategyRobustnessEvidence, ...]

    @model_validator(mode="after")
    def validate_common_samples(self) -> OperationalRobustnessStudyResult:
        if not self.strategies:
            raise ValueError("operational robustness study requires at least one strategy")
        ids = [item.strategy_id for item in self.strategies]
        if len(ids) != len(set(ids)):
            raise ValueError("operational robustness strategy ids must be unique")
        common = self.strategies[0].common_samples
        if any(item.common_samples != common for item in self.strategies[1:]):
            raise ValueError("all operational robustness strategies must use one common sample set")
        return self


def _execute_strategy(
    strategy_id: str,
    executor: StrategySampleExecutor,
    samples: tuple[dict[str, object], ...],
    common_samples: object,
) -> StrategyRobustnessEvidence:
    # common_samples is intentionally passed as a runtime object here so this helper
    # cannot create or mutate sampling identity; StrategyRobustnessEvidence performs
    # the exact type/alignment validation at construction time.
    outcomes: list[StrategyRealizationOutcome] = []
    for index, sample in enumerate(samples):
        sample_hash = sample.get("sample_sha256")
        if not isinstance(sample_hash, str):
            raise TypeError("generated common sample requires sample_sha256")
        try:
            completed = executor(sample)
        except Exception as exc:  # noqa: BLE001 - execution failure is evidence, not adapter failure.
            outcomes.append(
                StrategyRealizationOutcome(
                    realization=index,
                    sample_sha256=sample_hash,
                    status=RealizationStatus.FAILED,
                    failure_reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if completed is None:
            outcomes.append(
                StrategyRealizationOutcome(
                    realization=index,
                    sample_sha256=sample_hash,
                    status=RealizationStatus.MISSING,
                    failure_reason="strategy executor returned no realization result",
                )
            )
            continue
        if completed.realization != index:
            raise ValueError("completed strategy result realization does not match common sample")
        if completed.sample_sha256 != sample_hash:
            raise ValueError("completed strategy result sample hash does not match common sample")
        outcomes.append(
            StrategyRealizationOutcome(
                realization=index,
                sample_sha256=sample_hash,
                status=RealizationStatus.COMPLETED,
                metrics=dict(sorted(completed.metrics.items())),
                violations=dict(sorted(completed.violations.items())),
                authority_backend=completed.authority_backend,
                authority_force_model_fingerprint=completed.authority_force_model_fingerprint,
            )
        )
    return StrategyRobustnessEvidence(
        strategy_id=strategy_id,
        common_samples=common_samples,  # type: ignore[arg-type]
        outcomes=tuple(outcomes),
    )


def run_operational_robustness_study(
    config: RobustnessCampaignConfig,
    executors: Mapping[str, StrategySampleExecutor],
    *,
    sample_generator: SampleGenerator = generate_campaign_samples,
) -> OperationalRobustnessStudyResult:
    """Run every strategy on one pre-generated common-random-number sample set.

    Sampling occurs exactly once through the existing uncertainty engine (or an
    injected wrapper around that same engine for testing). This adapter contains
    no RNG and no propagation implementation.
    """

    if not executors:
        raise ValueError("operational robustness study requires strategy executors")
    samples = sample_generator(config)
    common = common_sample_set_from_generated(config, samples)
    strategies = tuple(
        _execute_strategy(strategy_id, executor, samples, common)
        for strategy_id, executor in sorted(executors.items())
    )
    return OperationalRobustnessStudyResult(strategies=strategies)
