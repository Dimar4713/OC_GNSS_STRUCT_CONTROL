from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, MutableMapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constellation_control.control.policies import CorrectionPolicy
from constellation_control.optimization.hybrid import (
    AuthoritativeStateAnchor,
    EventValidationEvidence,
    ScreeningEventBracket,
    ValidationOutcomeKind,
)
from constellation_control.optimization.hybrid_authority import HybridCorrectionAuthorityReceipt
from constellation_control.optimization.operations import CredibilityState


class HybridValidationJob(BaseModel):
    """Immutable identity of one required hybrid validation window."""

    model_config = ConfigDict(frozen=True)

    screening: ScreeningEventBracket
    anchor: AuthoritativeStateAnchor
    policy: CorrectionPolicy
    corridor_half_width_rad: float = Field(gt=0.0)
    validation_output_step_s: float = Field(gt=0.0)
    authority_config_identity: str
    correction_authority_required: bool = True
    correction_authority_identity: str | None = None

    @model_validator(mode="after")
    def validate_authority_identity(self) -> HybridValidationJob:
        if self.correction_authority_required and self.correction_authority_identity is None:
            raise ValueError("correction-authority-required job needs correction_authority_identity")
        return self

    @property
    def strategy_id(self) -> str:
        return self.screening.strategy_id

    @property
    def event_id(self) -> str:
        return self.screening.event_id

    def exact_key(self) -> str:
        payload = {
            "screening": self.screening.model_dump(mode="json"),
            "anchor": self.anchor.model_dump(mode="json"),
            "policy": self.policy.value,
            "corridor_half_width_rad": self.corridor_half_width_rad,
            "validation_output_step_s": self.validation_output_step_s,
            "authority_config_identity": self.authority_config_identity,
            "correction_authority_required": self.correction_authority_required,
            "correction_authority_identity": self.correction_authority_identity,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class HybridEventExecutionEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_validation: EventValidationEvidence
    correction_authority_receipt: HybridCorrectionAuthorityReceipt | None = None

    @model_validator(mode="after")
    def validate_linkage(self) -> HybridEventExecutionEvidence:
        receipt = self.correction_authority_receipt
        if receipt is not None and receipt.event_validation != self.event_validation:
            raise ValueError("correction authority receipt must link to the exact event validation")
        return self


class HybridEventExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    validation_key: str
    reused: bool
    evidence: HybridEventExecutionEvidence | None


class HybridStrategyValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    required_event_ids: tuple[str, ...]
    records: tuple[HybridEventExecutionRecord, ...]
    resulting_credibility_state: CredibilityState
    complete: bool
    reason: str | None = None


def put_hybrid_execution_cache(
    cache: MutableMapping[str, HybridEventExecutionEvidence],
    key: str,
    evidence: HybridEventExecutionEvidence,
) -> None:
    """Insert immutable evidence; conflicting content for one exact key fails closed."""

    previous = cache.get(key)
    if previous is not None and previous != evidence:
        raise ValueError("conflicting hybrid execution evidence for exact validation key")
    cache[key] = evidence


def _reduce_strategy(
    strategy_id: str,
    required_event_ids: tuple[str, ...],
    records: tuple[HybridEventExecutionRecord, ...],
    jobs_by_event: dict[str, HybridValidationJob],
) -> HybridStrategyValidationResult:
    by_event = {record.event_id: record for record in records}
    for event_id in required_event_ids:
        record = by_event[event_id]
        if record.evidence is None:
            return HybridStrategyValidationResult(
                strategy_id=strategy_id,
                required_event_ids=required_event_ids,
                records=records,
                resulting_credibility_state=CredibilityState.CANDIDATE_AWAITING_VALIDATION,
                complete=False,
                reason=f"missing-authoritative-validation:{event_id}",
            )
        validation = record.evidence.event_validation
        if validation.outcome in {
            ValidationOutcomeKind.EVENT_ABSENT,
            ValidationOutcomeKind.INVALID_STATE_ANCHOR,
            ValidationOutcomeKind.HARD_CONSTRAINT_REJECTED,
        }:
            return HybridStrategyValidationResult(
                strategy_id=strategy_id,
                required_event_ids=required_event_ids,
                records=records,
                resulting_credibility_state=CredibilityState.REJECTED_BY_AUTHORITY,
                complete=True,
                reason=f"{event_id}:{validation.outcome.value}",
            )
        if validation.outcome not in {
            ValidationOutcomeKind.CONFIRMED,
            ValidationOutcomeKind.SHIFTED,
        }:
            raise ValueError("unsupported validation outcome in strategy coverage")
        job = jobs_by_event[event_id]
        if job.correction_authority_required:
            receipt = record.evidence.correction_authority_receipt
            if receipt is None:
                return HybridStrategyValidationResult(
                    strategy_id=strategy_id,
                    required_event_ids=required_event_ids,
                    records=records,
                    resulting_credibility_state=CredibilityState.CANDIDATE_AWAITING_VALIDATION,
                    complete=False,
                    reason=f"missing-correction-authority:{event_id}",
                )
            if (
                receipt.resulting_credibility_state == CredibilityState.REJECTED_BY_AUTHORITY
                or not receipt.authorized
                or any(not margin.passed for margin in receipt.hard_constraints)
            ):
                return HybridStrategyValidationResult(
                    strategy_id=strategy_id,
                    required_event_ids=required_event_ids,
                    records=records,
                    resulting_credibility_state=CredibilityState.REJECTED_BY_AUTHORITY,
                    complete=True,
                    reason=f"{event_id}:correction-authority:{receipt.authority_reason}",
                )

    return HybridStrategyValidationResult(
        strategy_id=strategy_id,
        required_event_ids=required_event_ids,
        records=records,
        resulting_credibility_state=CredibilityState.AUTHORITATIVELY_VALIDATED_CANDIDATE,
        complete=True,
        reason=None,
    )


def run_hybrid_strategy_validation(
    jobs: tuple[HybridValidationJob, ...],
    *,
    executor: Callable[[HybridValidationJob], HybridEventExecutionEvidence | None],
    cache: MutableMapping[str, HybridEventExecutionEvidence] | None = None,
) -> HybridStrategyValidationResult:
    """Execute/reuse exact event jobs and reduce complete long-horizon strategy credibility."""

    if not jobs:
        raise ValueError("hybrid strategy validation requires at least one event job")
    strategy_id = jobs[0].strategy_id
    if any(job.strategy_id != strategy_id for job in jobs):
        raise ValueError("all hybrid validation jobs must belong to one strategy")

    jobs_by_event: dict[str, HybridValidationJob] = {}
    ordered_event_ids: list[str] = []
    for job in jobs:
        previous = jobs_by_event.get(job.event_id)
        if previous is None:
            jobs_by_event[job.event_id] = job
            ordered_event_ids.append(job.event_id)
        elif previous.exact_key() != job.exact_key():
            raise ValueError("same required event id has conflicting hybrid validation jobs")

    resolved_cache: MutableMapping[str, HybridEventExecutionEvidence] = {} if cache is None else cache
    record_by_event: dict[str, HybridEventExecutionRecord] = {}
    for job in jobs:
        key = job.exact_key()
        cached = resolved_cache.get(key)
        if cached is not None:
            evidence = cached
            reused = True
        else:
            evidence = executor(job)
            reused = False
            if evidence is not None:
                validation = evidence.event_validation
                if validation.strategy_id != job.strategy_id or validation.event_id != job.event_id:
                    raise ValueError("executor evidence does not match hybrid validation job")
                if validation.screening != job.screening:
                    raise ValueError("executor evidence screening bracket does not match validation job")
                put_hybrid_execution_cache(resolved_cache, key, evidence)
        previous_record = record_by_event.get(job.event_id)
        record = HybridEventExecutionRecord(
            event_id=job.event_id,
            validation_key=key,
            reused=reused,
            evidence=evidence,
        )
        if previous_record is None:
            record_by_event[job.event_id] = record
        elif previous_record.evidence != record.evidence:
            raise ValueError("duplicate exact hybrid job produced conflicting evidence")
        elif reused:
            record_by_event[job.event_id] = record

    records = tuple(record_by_event[event_id] for event_id in ordered_event_ids)
    return _reduce_strategy(
        strategy_id,
        tuple(ordered_event_ids),
        records,
        jobs_by_event,
    )
