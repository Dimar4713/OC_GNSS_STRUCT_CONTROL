from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.uncertainty.campaign import RobustnessCampaignConfig


class RealizationStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    MISSING = "missing"


class CommonSampleReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    realization: int = Field(ge=0)
    realization_seed: int = Field(ge=0)
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CommonSampleSetIdentity(BaseModel):
    """Common-random-number identity shared by every strategy in one robustness study."""

    model_config = ConfigDict(frozen=True)

    campaign_id: str
    master_seed: int
    sampling_model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    samples: tuple[CommonSampleReference, ...]

    @model_validator(mode="after")
    def validate_realization_order(self) -> CommonSampleSetIdentity:
        if not self.samples:
            raise ValueError("common sample set must contain at least one realization")
        for index, sample in enumerate(self.samples):
            if sample.realization != index:
                raise ValueError("common sample references must be ordered by contiguous realization index")
        hashes = [sample.sample_sha256 for sample in self.samples]
        if len(hashes) != len(set(hashes)):
            raise ValueError("common sample set contains duplicate sample hashes")
        return self

    @property
    def realization_count(self) -> int:
        return len(self.samples)


class StrategyRealizationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    realization: int = Field(ge=0)
    sample_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: RealizationStatus
    metrics: dict[str, float] = {}
    violations: dict[str, bool] = {}
    failure_reason: str | None = None
    authority_backend: str | None = None
    authority_force_model_fingerprint: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> StrategyRealizationOutcome:
        if self.status == RealizationStatus.COMPLETED:
            if self.failure_reason is not None:
                raise ValueError("completed realization cannot carry failure_reason")
        else:
            if not self.failure_reason:
                raise ValueError("failed/missing realization requires explicit failure_reason")
            if self.metrics or self.violations:
                raise ValueError("failed/missing realization cannot fabricate completed metrics/violations")
        return self


class StrategyRobustnessEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    common_samples: CommonSampleSetIdentity
    outcomes: tuple[StrategyRealizationOutcome, ...]
    incomplete_policy: str = "incomplete-counts-as-violation-v1"

    @model_validator(mode="after")
    def validate_alignment(self) -> StrategyRobustnessEvidence:
        if self.incomplete_policy != "incomplete-counts-as-violation-v1":
            raise ValueError("unsupported incomplete realization policy")
        if len(self.outcomes) != self.common_samples.realization_count:
            raise ValueError("strategy robustness outcomes must cover every common realization")
        for expected, outcome in zip(self.common_samples.samples, self.outcomes, strict=True):
            if outcome.realization != expected.realization:
                raise ValueError("strategy realization index is not aligned to common sample set")
            if outcome.sample_sha256 != expected.sample_sha256:
                raise ValueError("strategy realization sample hash is not aligned to common sample set")
        return self


class RobustnessAggregate(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_realizations: int = Field(gt=0)
    completed_realizations: int = Field(ge=0)
    failed_realizations: int = Field(ge=0)
    missing_realizations: int = Field(ge=0)
    incomplete_probability: float = Field(ge=0.0, le=1.0)
    conservative_violation_probability: dict[str, float]
    metric_statistics: dict[str, dict[str, float | int]]


class PairedMetricDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: str
    left_strategy_id: str
    right_strategy_id: str
    paired_complete_count: int = Field(ge=0)
    mean_left_minus_right: float | None
    minimum_left_minus_right: float | None
    maximum_left_minus_right: float | None


def uncertainty_sampling_model_sha256(config: RobustnessCampaignConfig) -> str:
    """Hash only fields that determine generated uncertainty samples, excluding workers/resume/report policy."""

    payload = {
        "samples": config.samples,
        "seed": config.seed,
        "scalar_uncertainties": [item.model_dump(mode="json") for item in config.scalar_uncertainties],
        "correlated_normal_groups": [
            item.model_dump(mode="json") for item in config.correlated_normal_groups
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def common_sample_set_from_generated(
    config: RobustnessCampaignConfig,
    samples: tuple[dict[str, object], ...],
) -> CommonSampleSetIdentity:
    """Capture identity from samples generated by the existing uncertainty engine; this function does not sample."""

    if len(samples) != config.samples:
        raise ValueError("generated sample count does not match robustness campaign configuration")
    references: list[CommonSampleReference] = []
    for index, sample in enumerate(samples):
        realization = sample.get("realization")
        seed = sample.get("realization_seed")
        sample_hash = sample.get("sample_sha256")
        if isinstance(realization, bool) or not isinstance(realization, int):
            raise TypeError("generated robustness realization must be an integer")
        if realization != index:
            raise ValueError("generated robustness samples must remain in realization order")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("generated robustness realization_seed must be an integer")
        if not isinstance(sample_hash, str):
            raise TypeError("generated robustness sample_sha256 must be a string")
        references.append(
            CommonSampleReference(
                realization=realization,
                realization_seed=seed,
                sample_sha256=sample_hash,
            )
        )
    return CommonSampleSetIdentity(
        campaign_id=config.campaign_id,
        master_seed=config.seed,
        sampling_model_sha256=uncertainty_sampling_model_sha256(config),
        samples=tuple(references),
    )


def aggregate_strategy_robustness(evidence: StrategyRobustnessEvidence) -> RobustnessAggregate:
    """Aggregate with a conservative denominator: every failed/missing realization counts as a violation."""

    total = len(evidence.outcomes)
    completed = [item for item in evidence.outcomes if item.status == RealizationStatus.COMPLETED]
    failed = sum(item.status == RealizationStatus.FAILED for item in evidence.outcomes)
    missing = sum(item.status == RealizationStatus.MISSING for item in evidence.outcomes)
    incomplete = failed + missing

    violation_names = sorted({name for item in completed for name in item.violations})
    conservative_violation_probability = {
        name: (
            incomplete + sum(bool(item.violations.get(name, False)) for item in completed)
        )
        / total
        for name in violation_names
    }
    conservative_violation_probability["incomplete_realization"] = incomplete / total

    metric_names = sorted({name for item in completed for name in item.metrics})
    metric_statistics: dict[str, dict[str, float | int]] = {}
    for name in metric_names:
        values = [item.metrics[name] for item in completed if name in item.metrics]
        if not values:
            continue
        metric_statistics[name] = {
            "count": len(values),
            "minimum": min(values),
            "mean": sum(values) / len(values),
            "maximum": max(values),
        }
    return RobustnessAggregate(
        total_realizations=total,
        completed_realizations=len(completed),
        failed_realizations=failed,
        missing_realizations=missing,
        incomplete_probability=incomplete / total,
        conservative_violation_probability=conservative_violation_probability,
        metric_statistics=metric_statistics,
    )


def paired_metric_delta(
    left: StrategyRobustnessEvidence,
    right: StrategyRobustnessEvidence,
    metric: str,
) -> PairedMetricDelta:
    """Compute aligned left-right deltas only where both strategies completed the exact same realization."""

    if left.common_samples != right.common_samples:
        raise ValueError("paired robustness comparison requires identical common sample-set identity")
    deltas: list[float] = []
    for left_item, right_item in zip(left.outcomes, right.outcomes, strict=True):
        if (
            left_item.status == RealizationStatus.COMPLETED
            and right_item.status == RealizationStatus.COMPLETED
            and metric in left_item.metrics
            and metric in right_item.metrics
        ):
            deltas.append(left_item.metrics[metric] - right_item.metrics[metric])
    return PairedMetricDelta(
        metric=metric,
        left_strategy_id=left.strategy_id,
        right_strategy_id=right.strategy_id,
        paired_complete_count=len(deltas),
        mean_left_minus_right=None if not deltas else sum(deltas) / len(deltas),
        minimum_left_minus_right=None if not deltas else min(deltas),
        maximum_left_minus_right=None if not deltas else max(deltas),
    )
