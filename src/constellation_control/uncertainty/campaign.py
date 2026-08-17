from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DistributionKind(StrEnum):
    NORMAL = "normal"
    UNIFORM = "uniform"
    BERNOULLI = "bernoulli"


class ScalarUncertaintyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    distribution: DistributionKind
    mean: float = 0.0
    sigma: float | None = None
    low: float | None = None
    high: float | None = None
    probability_true: float | None = None

    @model_validator(mode="after")
    def validate_distribution(self) -> ScalarUncertaintyConfig:
        values = (self.mean, self.sigma, self.low, self.high, self.probability_true)
        if any(value is not None and not np.isfinite(value) for value in values):
            raise ValueError("uncertainty distribution parameters must be finite")
        if self.distribution == DistributionKind.NORMAL:
            if self.sigma is None or self.sigma <= 0.0:
                raise ValueError("normal uncertainty requires sigma > 0")
            if self.low is not None or self.high is not None or self.probability_true is not None:
                raise ValueError("normal uncertainty does not accept uniform/Bernoulli parameters")
        elif self.distribution == DistributionKind.UNIFORM:
            if self.low is None or self.high is None or self.high <= self.low:
                raise ValueError("uniform uncertainty requires finite high > low")
            if self.sigma is not None or self.probability_true is not None:
                raise ValueError("uniform uncertainty does not accept normal/Bernoulli parameters")
        else:
            if self.probability_true is None or not 0.0 <= self.probability_true <= 1.0:
                raise ValueError("Bernoulli uncertainty requires probability_true in [0, 1]")
            if self.sigma is not None or self.low is not None or self.high is not None:
                raise ValueError("Bernoulli uncertainty does not accept normal/uniform parameters")
        return self


class CorrelatedNormalGroupConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_id: str = Field(min_length=1)
    names: tuple[str, ...]
    covariance: tuple[tuple[float, ...], ...]
    mean: tuple[float, ...] = ()

    @model_validator(mode="after")
    def validate_covariance(self) -> CorrelatedNormalGroupConfig:
        if len(self.names) < 2 or len(set(self.names)) != len(self.names):
            raise ValueError("correlated normal group requires at least two unique names")
        size = len(self.names)
        if len(self.covariance) != size or any(len(row) != size for row in self.covariance):
            raise ValueError("covariance shape must match correlated variable count")
        covariance = np.asarray(self.covariance, dtype=float)
        if not np.all(np.isfinite(covariance)):
            raise ValueError("covariance must be finite")
        if not np.allclose(covariance, covariance.T, rtol=0.0, atol=1.0e-14):
            raise ValueError("covariance must be symmetric")
        if np.min(np.linalg.eigvalsh(covariance)) < -1.0e-14:
            raise ValueError("covariance must be positive semidefinite")
        if self.mean and len(self.mean) != size:
            raise ValueError("correlated normal mean must match variable count")
        if self.mean and not np.all(np.isfinite(np.asarray(self.mean, dtype=float))):
            raise ValueError("correlated normal mean must be finite")
        return self


class WorstDirection(StrEnum):
    MAX = "max"
    MIN = "min"


class RobustnessCampaignConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    campaign_id: str = Field(min_length=1)
    samples: int = Field(gt=0)
    workers: int = Field(gt=0)
    seed: int
    accepted_candidate_id: str = Field(min_length=1)
    scalar_uncertainties: tuple[ScalarUncertaintyConfig, ...] = ()
    correlated_normal_groups: tuple[CorrelatedNormalGroupConfig, ...] = ()
    worst_metric: str = Field(min_length=1)
    worst_direction: WorstDirection = WorstDirection.MAX
    resume: bool = True

    @model_validator(mode="after")
    def validate_variable_names(self) -> RobustnessCampaignConfig:
        names: list[str] = [item.name for item in self.scalar_uncertainties]
        for group in self.correlated_normal_groups:
            names.extend(group.names)
        if not names:
            raise ValueError("robustness campaign requires at least one uncertainty variable")
        if len(names) != len(set(names)):
            raise ValueError("uncertainty variable names must be unique across the campaign")
        group_ids = [group.group_id for group in self.correlated_normal_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("correlated normal group_id values must be unique")
        return self


@dataclass(frozen=True)
class RobustnessCampaignResult:
    samples: tuple[dict[str, object], ...]
    outcomes: tuple[dict[str, object], ...]
    summary: dict[str, object]
    output_dir: Path


def campaign_config_hash(config: RobustnessCampaignConfig) -> str:
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sample_hash(sample: Mapping[str, object]) -> str:
    payload = json.dumps(dict(sample), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_campaign_samples(config: RobustnessCampaignConfig) -> tuple[dict[str, object], ...]:
    """Generate every realization before dispatch so worker count cannot change sampling."""

    rng = np.random.default_rng(config.seed)
    scalar = sorted(config.scalar_uncertainties, key=lambda item: item.name)
    groups = sorted(config.correlated_normal_groups, key=lambda item: item.group_id)
    samples: list[dict[str, object]] = []
    for realization in range(config.samples):
        sample: dict[str, object] = {
            "realization": realization,
            "realization_seed": int(rng.integers(0, 2**63 - 1)),
        }
        for item in scalar:
            if item.distribution == DistributionKind.NORMAL:
                sample[item.name] = float(rng.normal(item.mean, item.sigma))
            elif item.distribution == DistributionKind.UNIFORM:
                sample[item.name] = float(rng.uniform(item.low, item.high))
            else:
                sample[item.name] = bool(rng.random() < float(item.probability_true))
        for group in groups:
            mean = np.zeros(len(group.names), dtype=float) if not group.mean else np.asarray(group.mean, dtype=float)
            values = rng.multivariate_normal(mean, np.asarray(group.covariance, dtype=float), check_valid="raise")
            for name, value in zip(group.names, values, strict=True):
                sample[name] = float(value)
        sample["sample_sha256"] = _sample_hash(sample)
        samples.append(sample)
    return tuple(samples)


def _flatten_numeric(value: object, prefix: str = "") -> dict[str, float]:
    flattened: dict[str, float] = {}
    if isinstance(value, bool):
        return flattened
    if isinstance(value, (int, float)):
        numeric = float(value)
        if np.isfinite(numeric) and prefix:
            flattened[prefix] = numeric
        return flattened
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "violations":
                continue
            child_prefix = str(key) if not prefix else f"{prefix}.{key}"
            flattened.update(_flatten_numeric(child, child_prefix))
    return flattened


def _violations(outcome: Mapping[str, object]) -> dict[str, bool]:
    raw = outcome.get("violations", {})
    if not isinstance(raw, Mapping):
        raise TypeError("campaign outcome 'violations' must be a mapping")
    result: dict[str, bool] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, bool):
            raise TypeError("campaign violations must contain str -> bool values")
        result[key] = value
    return result


def summarize_campaign(
    config: RobustnessCampaignConfig,
    outcomes: tuple[dict[str, object], ...],
) -> dict[str, object]:
    if not outcomes:
        raise ValueError("robustness campaign produced no outcomes")
    flattened = [_flatten_numeric(outcome) for outcome in outcomes]
    common_numeric = sorted(set.intersection(*(set(item) for item in flattened)))
    statistics: dict[str, dict[str, float]] = {}
    for key in common_numeric:
        values = np.asarray([item[key] for item in flattened], dtype=float)
        statistics[key] = {
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
            "worst": float(np.max(values) if config.worst_direction == WorstDirection.MAX else np.min(values)),
        }

    violation_maps = [_violations(outcome) for outcome in outcomes]
    violation_names = sorted({name for item in violation_maps for name in item})
    violation_probability = {
        name: sum(item.get(name, False) for item in violation_maps) / len(violation_maps)
        for name in violation_names
    }

    if config.worst_metric not in common_numeric:
        raise ValueError(f"configured worst_metric is not a common numeric outcome: {config.worst_metric}")
    metric_values = np.asarray([item[config.worst_metric] for item in flattened], dtype=float)
    worst_index = int(np.argmax(metric_values) if config.worst_direction == WorstDirection.MAX else np.argmin(metric_values))

    return {
        "statistics": statistics,
        "violation_probability": violation_probability,
        "worst_case": {
            "metric": config.worst_metric,
            "direction": config.worst_direction.value,
            "realization": worst_index,
            "value": float(metric_values[worst_index]),
            "outcome": outcomes[worst_index],
        },
    }


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _load_resumable_outcome(
    directory: Path,
    sample: Mapping[str, object],
    config_hash: str,
) -> dict[str, object] | None:
    sample_path = directory / "sample.json"
    outcome_path = directory / "outcome.json"
    if not sample_path.exists() and not outcome_path.exists():
        return None
    if not sample_path.exists() or not outcome_path.exists():
        raise RuntimeError(f"partial robustness realization cannot be resumed safely: {directory}")
    stored_sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if stored_sample.get("sample_sha256") != sample.get("sample_sha256"):
        raise RuntimeError(f"resumable sample fingerprint mismatch: {directory}")
    stored_outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    if stored_outcome.get("campaign_config_hash") != config_hash:
        raise RuntimeError(f"resumable campaign hash mismatch: {directory}")
    outcome = stored_outcome.get("outcome")
    if not isinstance(outcome, dict):
        raise RuntimeError(f"resumable outcome payload is invalid: {directory}")
    return outcome


def _persist_tables(output_dir: Path, samples: tuple[dict[str, object], ...], outcomes: tuple[dict[str, object], ...]) -> None:
    sample_frame = pd.DataFrame(samples)
    sample_frame.to_parquet(output_dir / "samples.parquet", index=False)
    sample_frame.to_csv(output_dir / "samples.csv", index=False)

    outcome_rows: list[dict[str, object]] = []
    for realization, outcome in enumerate(outcomes):
        row: dict[str, object] = {
            "realization": realization,
            "outcome_json": json.dumps(outcome, sort_keys=True, allow_nan=False),
        }
        row.update(_flatten_numeric(outcome))
        row.update({f"violation.{name}": violated for name, violated in _violations(outcome).items()})
        outcome_rows.append(row)
    outcome_frame = pd.DataFrame(outcome_rows)
    outcome_frame.to_parquet(output_dir / "outcomes.parquet", index=False)
    outcome_frame.to_csv(output_dir / "outcomes.csv", index=False)


def run_robustness_campaign(
    config: RobustnessCampaignConfig,
    evaluator: Callable[[dict[str, object]], dict[str, object]],
    output_dir: Path,
    *,
    provenance: Mapping[str, object],
) -> RobustnessCampaignResult:
    """Execute a deterministic, bounded and resumable robustness campaign."""

    output_dir.mkdir(parents=True, exist_ok=True)
    config_hash = campaign_config_hash(config)
    samples = generate_campaign_samples(config)
    _atomic_json(
        output_dir / "campaign_manifest.json",
        {
            "campaign_id": config.campaign_id,
            "campaign_config_hash": config_hash,
            "config": config.model_dump(mode="json"),
            "provenance": dict(provenance),
        },
    )

    outcomes: list[dict[str, object] | None] = [None] * len(samples)
    pending: list[tuple[int, dict[str, object], Path]] = []
    for index, sample in enumerate(samples):
        realization_dir = output_dir / "realizations" / f"{index:06d}"
        resumed = _load_resumable_outcome(realization_dir, sample, config_hash) if config.resume else None
        if resumed is not None:
            outcomes[index] = resumed
        else:
            _atomic_json(realization_dir / "sample.json", sample)
            pending.append((index, sample, realization_dir))

    def evaluate(item: tuple[int, dict[str, object], Path]) -> tuple[int, dict[str, object], Path]:
        index, sample, realization_dir = item
        outcome = evaluator(dict(sample))
        if not isinstance(outcome, dict):
            raise TypeError("robustness evaluator must return dict[str, object]")
        _violations(outcome)
        _atomic_json(
            realization_dir / "outcome.json",
            {
                "campaign_config_hash": config_hash,
                "sample_sha256": sample["sample_sha256"],
                "outcome": outcome,
            },
        )
        return index, outcome, realization_dir

    if pending:
        if config.workers == 1:
            completed = map(evaluate, pending)
            for index, outcome, _ in completed:
                outcomes[index] = outcome
        else:
            with ThreadPoolExecutor(max_workers=config.workers) as pool:
                for index, outcome, _ in pool.map(evaluate, pending):
                    outcomes[index] = outcome

    if any(outcome is None for outcome in outcomes):
        raise RuntimeError("robustness campaign ended with incomplete realizations")
    complete_outcomes = tuple(outcome for outcome in outcomes if outcome is not None)
    summary = summarize_campaign(config, complete_outcomes)
    _persist_tables(output_dir, samples, complete_outcomes)
    _atomic_json(output_dir / "summary.json", summary)

    markdown = "\n".join(
        (
            f"# Robustness campaign: {config.campaign_id}",
            "",
            f"- Realizations: `{len(samples)}`",
            f"- Workers: `{config.workers}`",
            f"- Seed: `{config.seed}`",
            f"- Accepted candidate: `{config.accepted_candidate_id}`",
            f"- Worst metric: `{config.worst_metric}` ({config.worst_direction.value})",
            f"- Worst realization: `{summary['worst_case']['realization']}`",
            "",
            "All random samples are generated before parallel dispatch. Resumed realizations are accepted only when sample and campaign fingerprints match.",
        )
    ) + "\n"
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
    (output_dir / "report.html").write_text(
        f"<html><body><pre>{html.escape(markdown)}</pre></body></html>",
        encoding="utf-8",
    )
    return RobustnessCampaignResult(samples=samples, outcomes=complete_outcomes, summary=summary, output_dir=output_dir)
