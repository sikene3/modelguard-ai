"""Threshold, metrics, null, reliability, and baseline reference-vector tests."""

from __future__ import annotations

import json

import numpy as np
import pytest

from modelguard.core.serialization import canonical_json_bytes
from modelguard.data.generator import generate_synthetic_data
from modelguard.data.schema import FEATURE_ORDER
from modelguard.data.split import membership_hash
from modelguard.training.baseline import build_baseline_profile
from modelguard.training.config import TrainingConfig
from modelguard.training.evaluate import (
    ThresholdCandidate,
    ThresholdContract,
    build_reliability_bins,
    evaluate_held_out_test,
    safe_ratio,
    select_validation_threshold,
    validation_label_score_hash,
)


def _locked_threshold(value: float = 0.5) -> ThresholdContract:
    numerator = int(value * 1000)
    ids = ["syn-v1-00000000000000000000000000000000"]
    labels = np.asarray([0], dtype=int)
    scores = np.asarray([0.1], dtype=float)
    return ThresholdContract(
        model_version="1.0.0",
        locked_at="2026-01-01T00:00:00Z",
        comparison="score >= threshold",
        threshold=value,
        threshold_numerator=numerator,
        tie_policy="cost_then_fewer_fn_then_fewer_fp_then_lowest_threshold",
        validation_row_count=1,
        validation_membership_hash=membership_hash(ids),
        validation_label_score_hash=validation_label_score_hash(ids, labels, scores),
        selected_false_negatives=0,
        selected_false_positives=0,
        selected_synthetic_cost=0,
    )


def test_threshold_grid_and_ties_prioritize_fn_then_fp_then_lowest(
    training_config: TrainingConfig,
) -> None:
    labels = np.asarray([1, *([0] * 10)], dtype=int)
    scores = np.asarray([0.5] * 11, dtype=float)
    event_ids = [f"syn-v1-{index:032x}" for index in range(11)]

    evidence = select_validation_threshold(
        labels,
        scores,
        event_ids,
        training_config.threshold,
    )

    assert len(evidence.candidates) == 1001
    assert [item.threshold_numerator for item in evidence.candidates] == list(range(1001))
    assert evidence.selected.threshold == 0.0
    assert evidence.selected.false_negatives == 0
    assert evidence.selected.false_positives == 10
    assert evidence.selected.synthetic_cost == 10


def test_threshold_candidate_rejects_cost_that_does_not_reconcile() -> None:
    with pytest.raises(ValueError, match=r"10\*FN \+ FP"):
        ThresholdCandidate(
            threshold_numerator=500,
            threshold=0.5,
            false_negatives=1,
            false_positives=2,
            synthetic_cost=11,
        )


def test_known_vector_metrics_ap_lift_and_test_reference_cost() -> None:
    labels = np.asarray([0, 0, 1, 1], dtype=int)
    scores = np.asarray([0.1, 0.4, 0.35, 0.8], dtype=float)
    metrics = evaluate_held_out_test(labels, scores, _locked_threshold())

    assert metrics.average_precision.value == pytest.approx(5 / 6)
    assert metrics.prevalence.value == 0.5
    assert metrics.ap_lift.value == pytest.approx(5 / 3)
    assert metrics.roc_auc.value == 0.75
    assert metrics.confusion_counts.model_dump() == {
        "true_negatives": 2,
        "false_positives": 0,
        "false_negatives": 1,
        "true_positives": 1,
    }
    assert metrics.synthetic_cost == 10
    assert metrics.synthetic_cost_per_event.value == 2.5


def test_reliability_bins_are_half_open_with_final_score_one_inclusive() -> None:
    labels = np.asarray([0, 1], dtype=int)
    scores = np.asarray([0.0, 1.0], dtype=float)
    bins = build_reliability_bins(labels, scores)

    assert bins[0].interval == "[0.0,0.1)"
    assert bins[0].count == 1
    assert bins[9].interval == "[0.9,1.0]"
    assert bins[9].upper_inclusive is True
    assert bins[9].count == 1
    assert bins[4].mean_score.value is None
    assert bins[4].mean_score.numerator == 0.0
    assert bins[4].mean_score.denominator == 0
    assert bins[4].mean_score.reason == "empty_bin"


def test_undefined_results_serialize_as_json_null_never_nan_or_infinity() -> None:
    undefined = safe_ratio(0, 0, zero_reason="zero_denominator")
    payload = canonical_json_bytes(undefined).decode("utf-8")

    assert json.loads(payload)["value"] is None
    assert '"numerator":0' in payload
    assert '"denominator":0' in payload
    assert "NaN" not in payload
    assert "Infinity" not in payload

    single_class = evaluate_held_out_test(
        np.asarray([0, 0]), np.asarray([0.2, 0.3]), _locked_threshold()
    )
    assert single_class.average_precision.value is None
    assert single_class.roc_auc.value is None
    assert single_class.ap_lift.value is None


def test_baseline_collapses_constant_bins_and_has_explicit_outer_semantics(
    training_config: TrainingConfig,
) -> None:
    dataset = generate_synthetic_data(120, seed=77).set_index("event_id")
    features = dataset.loc[:, FEATURE_ORDER].copy()
    features["amount"] = 42.0
    scores = np.linspace(0.0, 1.0, len(features))
    baseline = build_baseline_profile(
        features,
        scores,
        _locked_threshold(),
        training_config.baseline,
        model_version="1.0.0",
        created_at="2026-01-01T00:00:00Z",
    )

    amount = baseline.numeric_features["amount"]
    assert amount.constant is True
    assert amount.collapsed_reference_edges == [42.0]
    assert [item.semantic for item in amount.bins] == [
        "underflow",
        "constant_reference",
        "overflow",
    ]
    assert amount.bins[0].lower_bound is None
    assert amount.bins[-1].upper_bound is None
    assert amount.bins[1].count == len(features)
    assert baseline.categorical_features["country_code"].universe[-2:] == [
        "__OTHER__",
        "__MISSING__",
    ]
    serialized = baseline.model_dump_json()
    assert "Infinity" not in serialized
    assert "NaN" not in serialized


def test_baseline_uses_only_supplied_training_rows(training_config: TrainingConfig) -> None:
    dataset = generate_synthetic_data(150, seed=88).set_index("event_id")
    training = dataset.iloc[:100].loc[:, FEATURE_ORDER].copy()
    validation_and_test = dataset.iloc[100:].loc[:, FEATURE_ORDER].copy()
    scores = np.linspace(0.05, 0.95, len(training))
    before = build_baseline_profile(
        training,
        scores,
        _locked_threshold(),
        training_config.baseline,
        model_version="1.0.0",
        created_at="2026-01-01T00:00:00Z",
    )
    validation_and_test.loc[:, "amount"] = 25_000.0
    after = build_baseline_profile(
        training,
        scores,
        _locked_threshold(),
        training_config.baseline,
        model_version="1.0.0",
        created_at="2026-01-01T00:00:00Z",
    )

    assert before == after
    assert before.training_row_count == 100
    assert before.locked_decision_distribution.counts == {"low_risk": 50, "high_risk": 50}
