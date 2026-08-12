"""Strict delayed-label joining and labeled-subset performance evaluation."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

import numpy as np
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from modelguard.core.hashing import HashRecord, canonical_json_hash, sha256_bytes
from modelguard.core.serialization import (
    StrictArtifactModel,
    canonical_json_bytes,
    validate_strict_json_model,
)
from modelguard.inference.events import PredictionEventV1
from modelguard.monitoring.config import PERFORMANCE_SCOPE_WORDING, MonitoringConfig
from modelguard.monitoring.events import FrozenRawSnapshot, parse_strict_json_record
from modelguard.monitoring.state import PerformanceState, performance_state_from_delta


class StrictLabelModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


class DelayedLabelV1(StrictLabelModel):
    """Minimal, versioned local delayed-label row."""

    label_schema_version: Literal["modelguard.label.v1"]
    event_id: UUID
    label: Annotated[StrictInt, Field(ge=0, le=1)]
    labeled_at: AwareDatetime

    @field_validator("labeled_at", mode="before")
    @classmethod
    def require_z_text(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.endswith("Z"):
                raise ValueError("labeled_at text must end with Z")
            return datetime.fromisoformat(f"{value[:-1]}+00:00")
        return value

    @field_validator("labeled_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("labeled_at must use UTC")
        return value.astimezone(UTC)


class LabelCounts(StrictArtifactModel):
    raw: int = Field(ge=0)
    rejected: int = Field(ge=0)
    duplicate: int = Field(ge=0)
    conflicting: int = Field(ge=0)
    unique_valid: int = Field(ge=0)
    joined: int = Field(ge=0)
    orphan: int = Field(ge=0)
    missing: int = Field(ge=0)
    positive_joined: int = Field(ge=0)
    negative_joined: int = Field(ge=0)
    unknown_schema_version: int = Field(ge=0)

    @model_validator(mode="after")
    def reconcile(self) -> LabelCounts:
        if self.raw != self.rejected + self.duplicate + self.conflicting + self.unique_valid:
            raise ValueError("raw labels do not reconcile")
        if self.unique_valid != self.joined + self.orphan:
            raise ValueError("unique valid labels do not reconcile to joined plus orphan")
        if self.joined != self.positive_joined + self.negative_joined:
            raise ValueError("joined label classes do not reconcile")
        return self


class PerformanceConfusionCounts(StrictArtifactModel):
    true_negatives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    true_positives: int = Field(ge=0)


class LabeledPerformanceMetrics(StrictArtifactModel):
    evaluation_scope: Literal["labeled_subset_only"] = "labeled_subset_only"
    policy_description: Literal[
        "synthetic-policy cost on the labeled subset versus held-out synthetic reference"
    ] = PERFORMANCE_SCOPE_WORDING
    row_count: int = Field(gt=0)
    threshold: float = Field(ge=0.0, le=1.0)
    average_precision: float = Field(ge=0.0, le=1.0)
    prevalence: float = Field(gt=0.0, lt=1.0)
    ap_lift: float = Field(ge=0.0)
    roc_auc: float = Field(ge=0.0, le=1.0)
    brier_score: float = Field(ge=0.0, le=1.0)
    log_loss: float = Field(ge=0.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    confusion_counts: PerformanceConfusionCounts
    synthetic_cost: int = Field(ge=0)
    synthetic_cost_per_event: float = Field(ge=0.0)
    held_out_synthetic_reference_cost_per_event: float = Field(ge=0.0)
    synthetic_cost_delta: float


class PerformanceEvaluation(StrictArtifactModel):
    state: PerformanceState
    reason: str
    label_source_configured: bool
    label_schema_version: Literal["modelguard.label.v1"]
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    counts: LabelCounts
    adequacy_requirements: dict[str, int | float]
    label_record_multiset_hash: HashRecord
    metrics: LabeledPerformanceMetrics | None
    interpretation: Literal[
        "synthetic-policy cost on the labeled subset versus held-out synthetic reference"
    ] = PERFORMANCE_SCOPE_WORDING
    limitation: Literal[
        "partial-label selection bias may make the labeled subset unrepresentative"
    ] = "partial-label selection bias may make the labeled subset unrepresentative"


@dataclass(frozen=True)
class EvaluatedPerformance:
    evaluation: PerformanceEvaluation
    classified_label_digests: tuple[str, ...]


def _empty_label_hash() -> HashRecord:
    return canonical_json_hash(
        [],
        ordering="label classification then canonical label-record digest ascending as a multiset",
        exclusions=["enumeration order", "storage object name", "file boundary"],
    )


def _requirements(config: MonitoringConfig) -> dict[str, int | float]:
    return {
        "minimum_coverage": config.minimum_label_coverage,
        "minimum_labeled_rows": config.minimum_labeled_rows,
        "minimum_positive_labels": config.minimum_positive_labels,
        "minimum_negative_labels": config.minimum_negative_labels,
    }


def _unknown_or_pending_evaluation(
    *,
    state: PerformanceState,
    reason: str,
    configured: bool,
    accepted_count: int,
    counts: LabelCounts | None,
    coverage: float | None,
    label_hash: HashRecord,
    config: MonitoringConfig,
) -> PerformanceEvaluation:
    actual_counts = counts or LabelCounts(
        raw=0,
        rejected=0,
        duplicate=0,
        conflicting=0,
        unique_valid=0,
        joined=0,
        orphan=0,
        missing=accepted_count,
        positive_joined=0,
        negative_joined=0,
        unknown_schema_version=0,
    )
    return PerformanceEvaluation(
        state=state,
        reason=reason,
        label_source_configured=configured,
        label_schema_version=config.label_schema_version,
        coverage=coverage,
        counts=actual_counts,
        adequacy_requirements=_requirements(config),
        label_record_multiset_hash=label_hash,
        metrics=None,
    )


def evaluate_delayed_performance(
    events: tuple[PredictionEventV1, ...],
    *,
    label_snapshot: FrozenRawSnapshot | None,
    locked_threshold: float,
    held_out_reference_cost_per_event: float,
    config: MonitoringConfig,
) -> EvaluatedPerformance:
    """Join strict labels and compute metrics only after every adequacy boundary passes."""

    if label_snapshot is None:
        return EvaluatedPerformance(
            evaluation=_unknown_or_pending_evaluation(
                state=PerformanceState.UNKNOWN,
                reason="no_label_source_configured",
                configured=False,
                accepted_count=len(events),
                counts=None,
                coverage=None,
                label_hash=_empty_label_hash(),
                config=config,
            ),
            classified_label_digests=(),
        )
    if (
        not math.isfinite(held_out_reference_cost_per_event)
        or held_out_reference_cost_per_event < 0
    ):
        raise ValueError("held-out synthetic reference cost must be finite and non-negative")
    if not math.isfinite(locked_threshold) or not 0.0 <= locked_threshold <= 1.0:
        raise ValueError("locked threshold must be finite in [0, 1]")

    groups: dict[str, list[tuple[DelayedLabelV1, str]]] = defaultdict(list)
    rejected = 0
    duplicate = 0
    conflicting = 0
    unknown_versions = 0
    schema_fault = False
    classified_digests: list[str] = []
    for raw, fallback_digest in zip(
        label_snapshot.records, label_snapshot.record_digests, strict=True
    ):
        try:
            parsed = parse_strict_json_record(raw)
        except (UnicodeError, ValueError):
            rejected += 1
            schema_fault = True
            classified_digests.append(f"rejected:{fallback_digest}")
            continue
        if (
            isinstance(parsed, dict)
            and "label_schema_version" in parsed
            and parsed["label_schema_version"] != config.label_schema_version
        ):
            unknown_versions += 1
        try:
            label = validate_strict_json_model(canonical_json_bytes(parsed), DelayedLabelV1)
        except ValueError:
            rejected += 1
            schema_fault = True
            classified_digests.append(f"rejected:{fallback_digest}")
            continue
        digest = sha256_bytes(canonical_json_bytes(label))
        groups[str(label.event_id)].append((label, digest))

    unique_labels: dict[str, DelayedLabelV1] = {}
    for event_id in sorted(groups):
        group = groups[event_id]
        unique_digests = {digest for _, digest in group}
        if len(unique_digests) == 1:
            unique_labels[event_id] = group[0][0]
            duplicate += len(group) - 1
            classified_digests.extend(f"duplicate:{group[0][1]}" for _ in range(len(group) - 1))
        else:
            conflicting += len(group)
            classified_digests.extend(f"conflicting:{digest}" for _, digest in group)

    event_by_id = {str(event.event_id): event for event in events}
    joined_ids = sorted(set(event_by_id).intersection(unique_labels))
    orphan_ids = sorted(set(unique_labels) - set(event_by_id))
    for event_id in joined_ids:
        digest = sha256_bytes(canonical_json_bytes(unique_labels[event_id]))
        classified_digests.append(f"joined:{digest}")
    for event_id in orphan_ids:
        digest = sha256_bytes(canonical_json_bytes(unique_labels[event_id]))
        classified_digests.append(f"orphan:{digest}")

    joined_labels = [unique_labels[event_id] for event_id in joined_ids]
    positives = sum(label.label == 1 for label in joined_labels)
    negatives = len(joined_labels) - positives
    accepted_count = len(events)
    coverage = len(joined_ids) / accepted_count if accepted_count else 0.0
    counts = LabelCounts(
        raw=len(label_snapshot.records),
        rejected=rejected,
        duplicate=duplicate,
        conflicting=conflicting,
        unique_valid=len(unique_labels),
        joined=len(joined_ids),
        orphan=len(orphan_ids),
        missing=accepted_count - len(joined_ids),
        positive_joined=positives,
        negative_joined=negatives,
        unknown_schema_version=unknown_versions,
    )
    label_hash = canonical_json_hash(
        sorted(classified_digests),
        ordering="label classification then canonical label-record digest ascending as a multiset",
        exclusions=["enumeration order", "storage object name", "file boundary"],
    )
    if unknown_versions:
        evaluation = _unknown_or_pending_evaluation(
            state=PerformanceState.UNKNOWN,
            reason="unknown_label_schema_version",
            configured=True,
            accepted_count=accepted_count,
            counts=counts,
            coverage=coverage,
            label_hash=label_hash,
            config=config,
        )
        return EvaluatedPerformance(evaluation, tuple(sorted(classified_digests)))
    if conflicting:
        evaluation = _unknown_or_pending_evaluation(
            state=PerformanceState.UNKNOWN,
            reason="conflicting_label_group",
            configured=True,
            accepted_count=accepted_count,
            counts=counts,
            coverage=coverage,
            label_hash=label_hash,
            config=config,
        )
        return EvaluatedPerformance(evaluation, tuple(sorted(classified_digests)))
    if schema_fault:
        evaluation = _unknown_or_pending_evaluation(
            state=PerformanceState.UNKNOWN,
            reason="invalid_label_schema",
            configured=True,
            accepted_count=accepted_count,
            counts=counts,
            coverage=coverage,
            label_hash=label_hash,
            config=config,
        )
        return EvaluatedPerformance(evaluation, tuple(sorted(classified_digests)))

    adequate = (
        coverage >= config.minimum_label_coverage
        and len(joined_ids) >= config.minimum_labeled_rows
        and positives >= config.minimum_positive_labels
        and negatives >= config.minimum_negative_labels
    )
    if not adequate:
        evaluation = _unknown_or_pending_evaluation(
            state=PerformanceState.PENDING_LABELS,
            reason="configured_label_source_below_adequacy",
            configured=True,
            accepted_count=accepted_count,
            counts=counts,
            coverage=coverage,
            label_hash=label_hash,
            config=config,
        )
        return EvaluatedPerformance(evaluation, tuple(sorted(classified_digests)))

    labels = np.asarray([unique_labels[event_id].label for event_id in joined_ids], dtype=int)
    scores = np.asarray([event_by_id[event_id].score for event_id in joined_ids], dtype=float)
    decisions = scores >= locked_threshold
    matrix = confusion_matrix(labels, decisions, labels=[0, 1])
    true_negatives, false_positives, false_negatives, true_positives = (
        int(matrix[0, 0]),
        int(matrix[0, 1]),
        int(matrix[1, 0]),
        int(matrix[1, 1]),
    )
    synthetic_cost = (
        config.false_negative_cost * false_negatives + config.false_positive_cost * false_positives
    )
    cost_decimal = Decimal(synthetic_cost) / Decimal(len(labels))
    reference_decimal = Decimal(str(held_out_reference_cost_per_event))
    delta_decimal = cost_decimal - reference_decimal
    delta = float(delta_decimal)
    prevalence = float(labels.mean())
    average_precision = float(average_precision_score(labels, scores))
    metrics = LabeledPerformanceMetrics(
        row_count=len(labels),
        threshold=locked_threshold,
        average_precision=average_precision,
        prevalence=prevalence,
        ap_lift=average_precision / prevalence,
        roc_auc=float(roc_auc_score(labels, scores)),
        brier_score=float(brier_score_loss(labels, scores)),
        log_loss=float(log_loss(labels, scores, labels=[0, 1])),
        precision=float(precision_score(labels, decisions, zero_division=0)),
        recall=float(recall_score(labels, decisions, zero_division=0)),
        f1=float(f1_score(labels, decisions, zero_division=0)),
        confusion_counts=PerformanceConfusionCounts(
            true_negatives=true_negatives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            true_positives=true_positives,
        ),
        synthetic_cost=synthetic_cost,
        synthetic_cost_per_event=float(cost_decimal),
        held_out_synthetic_reference_cost_per_event=held_out_reference_cost_per_event,
        synthetic_cost_delta=delta,
    )
    evaluation = PerformanceEvaluation(
        state=performance_state_from_delta(delta, config),
        reason="adequate_labels_cost_delta_evaluated",
        label_source_configured=True,
        label_schema_version=config.label_schema_version,
        coverage=coverage,
        counts=counts,
        adequacy_requirements=_requirements(config),
        label_record_multiset_hash=label_hash,
        metrics=metrics,
    )
    return EvaluatedPerformance(evaluation, tuple(sorted(classified_digests)))
