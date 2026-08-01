"""Validation-only threshold selection and held-out evaluation contracts."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import Field, model_validator
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from modelguard.core.hashing import HashRecord, canonical_json_hash
from modelguard.core.serialization import StrictArtifactModel
from modelguard.data.split import membership_hash
from modelguard.training.config import ThresholdConfig


class MetricValue(StrictArtifactModel):
    """A finite metric or an explicit JSON-null result with support evidence."""

    value: float | None
    numerator: float | int | None
    denominator: float | int | None
    reason: str | None

    @model_validator(mode="after")
    def validate_definedness(self) -> MetricValue:
        finite_values = (self.value, self.numerator, self.denominator)
        if any(isinstance(item, float) and not math.isfinite(item) for item in finite_values):
            raise ValueError("metric values and supports must be finite")
        if self.value is None:
            if self.reason is None or self.numerator is None or self.denominator is None:
                raise ValueError("undefined metrics require numerator, denominator, and reason")
        elif self.reason is not None:
            raise ValueError("defined metrics cannot have an undefined reason")
        return self


def safe_ratio(
    numerator: float | int,
    denominator: float | int,
    *,
    zero_reason: str,
) -> MetricValue:
    """Divide without emitting NaN/Infinity and retain the exact operands."""

    if denominator == 0:
        return MetricValue(
            value=None,
            numerator=numerator,
            denominator=denominator,
            reason=zero_reason,
        )
    return MetricValue(
        value=float(numerator / denominator),
        numerator=numerator,
        denominator=denominator,
        reason=None,
    )


class ThresholdCandidate(StrictArtifactModel):
    """One integer-thousandth validation policy candidate."""

    threshold_numerator: int = Field(ge=0, le=1000)
    threshold: float = Field(ge=0.0, le=1.0)
    false_negatives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    synthetic_cost: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_cost(self) -> ThresholdCandidate:
        if self.synthetic_cost != 10 * self.false_negatives + self.false_positives:
            raise ValueError("threshold candidate cost must use the locked 10*FN + FP policy")
        return self


class ThresholdSelectionEvidence(StrictArtifactModel):
    """Namespaced evidence derived only from validation labels and scores."""

    contract_version: Literal["modelguard.validation-threshold-selection.v1"] = (
        "modelguard.validation-threshold-selection.v1"
    )
    evaluation_scope: Literal["validation_only"] = "validation_only"
    comparison: Literal["score >= threshold"]
    grid_start_numerator: Literal[0] = 0
    grid_end_numerator: Literal[1000] = 1000
    grid_denominator: Literal[1000] = 1000
    candidate_count: Literal[1001] = 1001
    false_negative_cost: Literal[10] = 10
    false_positive_cost: Literal[1] = 1
    tie_policy: Literal["cost_then_fewer_fn_then_fewer_fp_then_lowest_threshold"]
    validation_row_count: int = Field(gt=0)
    validation_membership_hash: HashRecord
    validation_label_score_hash: HashRecord
    selected: ThresholdCandidate
    candidates: list[ThresholdCandidate]

    @model_validator(mode="after")
    def validate_grid(self) -> ThresholdSelectionEvidence:
        if len(self.candidates) != 1001:
            raise ValueError(
                "threshold evidence must contain all 1001 integer-thousandth candidates"
            )
        for expected_numerator, candidate in enumerate(self.candidates):
            if candidate.threshold_numerator != expected_numerator:
                raise ValueError("threshold grid is not in exact integer-thousandth order")
            if candidate.threshold != expected_numerator / 1000:
                raise ValueError("threshold value does not match its exact numerator")
        expected_selected = min(
            self.candidates,
            key=lambda item: (
                item.synthetic_cost,
                item.false_negatives,
                item.false_positives,
                item.threshold_numerator,
            ),
        )
        if self.selected != expected_selected:
            raise ValueError("selected threshold does not implement the locked tie policy")
        return self


class ThresholdContract(StrictArtifactModel):
    """Locked deployed decision policy persisted before any test prediction."""

    contract_version: Literal["modelguard.threshold.v1"] = "modelguard.threshold.v1"
    model_version: str
    locked_at: str
    locked_before_test_evaluation: Literal[True] = True
    comparison: Literal["score >= threshold"]
    threshold: float = Field(ge=0.0, le=1.0)
    threshold_numerator: int = Field(ge=0, le=1000)
    grid_denominator: Literal[1000] = 1000
    false_negative_cost: Literal[10] = 10
    false_positive_cost: Literal[1] = 1
    tie_policy: Literal["cost_then_fewer_fn_then_fewer_fp_then_lowest_threshold"]
    validation_row_count: int = Field(gt=0)
    validation_membership_hash: HashRecord
    validation_label_score_hash: HashRecord
    selected_false_negatives: int = Field(ge=0)
    selected_false_positives: int = Field(ge=0)
    selected_synthetic_cost: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_exact_threshold(self) -> ThresholdContract:
        if self.threshold != self.threshold_numerator / self.grid_denominator:
            raise ValueError("threshold must equal its exact integer-thousandth representation")
        expected_cost = (
            self.false_negative_cost * self.selected_false_negatives
            + self.false_positive_cost * self.selected_false_positives
        )
        if self.selected_synthetic_cost != expected_cost:
            raise ValueError("selected threshold cost does not reconcile")
        return self


class ConfusionCounts(StrictArtifactModel):
    true_negatives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    true_positives: int = Field(ge=0)


class ConfusionRates(StrictArtifactModel):
    accuracy: MetricValue
    precision: MetricValue
    recall: MetricValue
    f1: MetricValue
    specificity: MetricValue
    false_positive_rate: MetricValue
    false_negative_rate: MetricValue
    predicted_positive_rate: MetricValue


class ReliabilityBin(StrictArtifactModel):
    index: int = Field(ge=0, le=9)
    interval: str
    lower_bound: float
    upper_bound: float
    lower_inclusive: Literal[True] = True
    upper_inclusive: bool
    count: int = Field(ge=0)
    mean_score: MetricValue
    observed_prevalence: MetricValue


class EvaluationMetrics(StrictArtifactModel):
    """Public held-out test evidence; no training-performance fields exist."""

    evaluation_scope: Literal["held_out_test_once_after_threshold_lock"] = (
        "held_out_test_once_after_threshold_lock"
    )
    row_count: int = Field(gt=0)
    threshold: float = Field(ge=0.0, le=1.0)
    average_precision: MetricValue
    prevalence: MetricValue
    ap_lift: MetricValue
    roc_auc: MetricValue
    brier_score: MetricValue
    log_loss: MetricValue
    confusion_counts: ConfusionCounts
    confusion_rates: ConfusionRates
    synthetic_cost: int = Field(ge=0)
    synthetic_cost_per_event: MetricValue
    reliability_bins: list[ReliabilityBin]

    @model_validator(mode="after")
    def validate_reliability_contract(self) -> EvaluationMetrics:
        if len(self.reliability_bins) != 10:
            raise ValueError("evaluation must contain exactly ten reliability bins")
        if sum(item.count for item in self.reliability_bins) != self.row_count:
            raise ValueError("reliability bin counts must reconcile to evaluation row count")
        counts = self.confusion_counts
        if (
            counts.true_negatives
            + counts.false_positives
            + counts.false_negatives
            + counts.true_positives
            != self.row_count
        ):
            raise ValueError("confusion counts must reconcile to evaluation row count")
        if self.synthetic_cost != 10 * counts.false_negatives + counts.false_positives:
            raise ValueError("synthetic cost must use the locked 10*FN + FP policy")
        return self


class MetricsContract(StrictArtifactModel):
    """Bundle evaluation artifact with separate validation selection evidence."""

    contract_version: Literal["modelguard.metrics.v1"] = "modelguard.metrics.v1"
    model_version: str
    created_at: str
    public_headline_scope: Literal["held_out_test"] = "held_out_test"
    held_out_test: EvaluationMetrics
    validation_threshold_selection: ThresholdSelectionEvidence


def validation_label_score_hash(
    event_ids: list[str],
    labels: np.ndarray,
    scores: np.ndarray,
) -> HashRecord:
    """Hash validation threshold inputs without exposing them in the bundle."""

    records = sorted(
        (
            {"event_id": event_id, "label": int(label), "score": float(score)}
            for event_id, label, score in zip(event_ids, labels, scores, strict=True)
        ),
        key=lambda item: str(item["event_id"]),
    )
    return canonical_json_hash(
        records,
        ordering="event_id lexicographic ascending; fields event_id, label, score",
        exclusions=[
            "validation physical row order",
            "validation feature values",
            "training rows",
            "test rows and labels",
        ],
    )


def select_validation_threshold(
    labels: np.ndarray,
    scores: np.ndarray,
    event_ids: list[str],
    config: ThresholdConfig,
) -> ThresholdSelectionEvidence:
    """Select the exact validation-only cost policy over all integer thousandths."""

    label_values = np.asarray(labels, dtype=int)
    score_values = np.asarray(scores, dtype=float)
    if len(label_values) == 0 or len(label_values) != len(score_values):
        raise ValueError("validation labels and scores must be non-empty and aligned")
    if len(event_ids) != len(label_values) or len(set(event_ids)) != len(event_ids):
        raise ValueError("validation event IDs must be unique and aligned")
    if not set(label_values.tolist()).issubset({0, 1}):
        raise ValueError("validation labels must be binary")
    if not np.isfinite(score_values).all() or ((score_values < 0) | (score_values > 1)).any():
        raise ValueError("validation scores must be finite and in [0, 1]")
    candidates: list[ThresholdCandidate] = []
    for numerator in range(config.grid_denominator + 1):
        threshold = numerator / config.grid_denominator
        decisions = score_values >= threshold
        false_negatives = int(((label_values == 1) & ~decisions).sum())
        false_positives = int(((label_values == 0) & decisions).sum())
        cost = (
            config.false_negative_cost * false_negatives
            + config.false_positive_cost * false_positives
        )
        candidates.append(
            ThresholdCandidate(
                threshold_numerator=numerator,
                threshold=threshold,
                false_negatives=false_negatives,
                false_positives=false_positives,
                synthetic_cost=cost,
            )
        )
    selected = min(
        candidates,
        key=lambda item: (
            item.synthetic_cost,
            item.false_negatives,
            item.false_positives,
            item.threshold_numerator,
        ),
    )
    return ThresholdSelectionEvidence(
        comparison=config.comparison,
        tie_policy=config.tie_policy,
        validation_row_count=len(label_values),
        validation_membership_hash=membership_hash(event_ids),
        validation_label_score_hash=validation_label_score_hash(
            event_ids, label_values, score_values
        ),
        selected=selected,
        candidates=candidates,
    )


def lock_threshold(
    model_version: str,
    evidence: ThresholdSelectionEvidence,
    *,
    locked_at: str,
) -> ThresholdContract:
    """Freeze validation selection evidence into the deployed threshold contract."""

    selected = evidence.selected
    return ThresholdContract(
        model_version=model_version,
        locked_at=locked_at,
        comparison=evidence.comparison,
        threshold=selected.threshold,
        threshold_numerator=selected.threshold_numerator,
        tie_policy=evidence.tie_policy,
        validation_row_count=evidence.validation_row_count,
        validation_membership_hash=evidence.validation_membership_hash,
        validation_label_score_hash=evidence.validation_label_score_hash,
        selected_false_negatives=selected.false_negatives,
        selected_false_positives=selected.false_positives,
        selected_synthetic_cost=selected.synthetic_cost,
    )


def build_reliability_bins(labels: np.ndarray, scores: np.ndarray) -> list[ReliabilityBin]:
    """Build exact [0,.1), ..., [.9,1] reliability summaries."""

    label_values = np.asarray(labels, dtype=int)
    score_values = np.asarray(scores, dtype=float)
    bins: list[ReliabilityBin] = []
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        if index == 9:
            mask = (score_values >= lower) & (score_values <= upper)
            interval = f"[{lower:.1f},{upper:.1f}]"
        else:
            mask = (score_values >= lower) & (score_values < upper)
            interval = f"[{lower:.1f},{upper:.1f})"
        count = int(mask.sum())
        score_sum = float(score_values[mask].sum())
        positive_count = int(label_values[mask].sum())
        bins.append(
            ReliabilityBin(
                index=index,
                interval=interval,
                lower_bound=lower,
                upper_bound=upper,
                upper_inclusive=index == 9,
                count=count,
                mean_score=safe_ratio(score_sum, count, zero_reason="empty_bin"),
                observed_prevalence=safe_ratio(positive_count, count, zero_reason="empty_bin"),
            )
        )
    return bins


def _supported_metric(
    value: float | None,
    numerator: float | int,
    denominator: float | int,
    reason: str | None,
) -> MetricValue:
    return MetricValue(
        value=value,
        numerator=numerator,
        denominator=denominator,
        reason=reason,
    )


def evaluate_held_out_test(
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: ThresholdContract,
) -> EvaluationMetrics:
    """Evaluate one held-out score vector only after receiving a locked policy."""

    label_values = np.asarray(labels, dtype=int)
    score_values = np.asarray(scores, dtype=float)
    row_count = len(label_values)
    if row_count == 0 or row_count != len(score_values):
        raise ValueError("test labels and scores must be non-empty and aligned")
    if not set(label_values.tolist()).issubset({0, 1}):
        raise ValueError("test labels must be binary")
    if not np.isfinite(score_values).all() or ((score_values < 0) | (score_values > 1)).any():
        raise ValueError("test scores must be finite and in [0, 1]")

    positives = int((label_values == 1).sum())
    negatives = row_count - positives
    prevalence = safe_ratio(positives, row_count, zero_reason="empty_evaluation")
    if positives == 0:
        average_precision = _supported_metric(
            None, positives, row_count, "average_precision_requires_positive_class"
        )
    else:
        average_precision = _supported_metric(
            float(average_precision_score(label_values, score_values)),
            positives,
            row_count,
            None,
        )
    average_precision_value = average_precision.value
    prevalence_value = prevalence.value
    if average_precision_value is None or prevalence_value is None or prevalence_value == 0.0:
        ap_lift = _supported_metric(
            None,
            average_precision_value or 0.0,
            prevalence_value or 0.0,
            "ap_lift_requires_nonzero_prevalence_and_defined_average_precision",
        )
    else:
        ap_lift = safe_ratio(
            average_precision_value,
            prevalence_value,
            zero_reason="zero_prevalence",
        )
    if positives == 0 or negatives == 0:
        roc_auc = _supported_metric(None, positives, negatives, "roc_auc_requires_both_classes")
    else:
        roc_auc = _supported_metric(
            float(roc_auc_score(label_values, score_values)), positives, negatives, None
        )

    squared_error_sum = float(np.square(score_values - label_values).sum())
    brier = _supported_metric(
        float(brier_score_loss(label_values, score_values)),
        squared_error_sum,
        row_count,
        None,
    )
    clipped_scores = np.clip(score_values, np.finfo(float).eps, 1 - np.finfo(float).eps)
    total_log_loss = float(
        -(
            label_values * np.log(clipped_scores) + (1 - label_values) * np.log(1 - clipped_scores)
        ).sum()
    )
    log_loss_metric = _supported_metric(
        float(log_loss(label_values, score_values, labels=[0, 1])),
        total_log_loss,
        row_count,
        None,
    )

    decisions = score_values >= threshold.threshold
    true_positives = int(((label_values == 1) & decisions).sum())
    false_negatives = int(((label_values == 1) & ~decisions).sum())
    false_positives = int(((label_values == 0) & decisions).sum())
    true_negatives = int(((label_values == 0) & ~decisions).sum())
    predicted_positives = true_positives + false_positives
    synthetic_cost = 10 * false_negatives + false_positives
    counts = ConfusionCounts(
        true_negatives=true_negatives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        true_positives=true_positives,
    )
    rates = ConfusionRates(
        accuracy=safe_ratio(
            true_positives + true_negatives, row_count, zero_reason="empty_evaluation"
        ),
        precision=safe_ratio(
            true_positives, predicted_positives, zero_reason="no_predicted_positives"
        ),
        recall=safe_ratio(true_positives, positives, zero_reason="no_positive_class"),
        f1=safe_ratio(
            2 * true_positives,
            2 * true_positives + false_positives + false_negatives,
            zero_reason="no_positive_predictions_or_labels",
        ),
        specificity=safe_ratio(true_negatives, negatives, zero_reason="no_negative_class"),
        false_positive_rate=safe_ratio(false_positives, negatives, zero_reason="no_negative_class"),
        false_negative_rate=safe_ratio(false_negatives, positives, zero_reason="no_positive_class"),
        predicted_positive_rate=safe_ratio(
            predicted_positives, row_count, zero_reason="empty_evaluation"
        ),
    )
    return EvaluationMetrics(
        row_count=row_count,
        threshold=threshold.threshold,
        average_precision=average_precision,
        prevalence=prevalence,
        ap_lift=ap_lift,
        roc_auc=roc_auc,
        brier_score=brier,
        log_loss=log_loss_metric,
        confusion_counts=counts,
        confusion_rates=rates,
        synthetic_cost=synthetic_cost,
        synthetic_cost_per_event=safe_ratio(
            synthetic_cost, row_count, zero_reason="empty_evaluation"
        ),
        reliability_bins=build_reliability_bins(label_values, score_values),
    )
