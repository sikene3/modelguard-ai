"""Transparent PSI, Jensen-Shannon distance, and frozen-baseline signal evaluation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Literal

import numpy as np
from pydantic import Field

from modelguard.core.serialization import StrictArtifactModel
from modelguard.inference.events import PredictionEventV1
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.state import DriftState
from modelguard.training.baseline import BaselineProfile, NumericFeatureProfile


class DriftSignal(StrictArtifactModel):
    name: str
    kind: Literal[
        "numeric_psi", "categorical_js_distance", "prediction_psi", "decision_js_distance"
    ]
    required: Literal[True] = True
    value: float | None = Field(default=None, ge=0.0)
    state: DriftState
    reason: str
    baseline_proportions: list[float]
    current_proportions: list[float]
    universe: list[str]


class MissingnessSignal(StrictArtifactModel):
    feature: str
    baseline_rate: float = Field(ge=0.0, le=1.0)
    current_rate: float = Field(ge=0.0, le=1.0)
    absolute_delta: float = Field(ge=0.0, le=1.0)
    state: Literal["valid", "warning", "invalid"]


class DriftEvaluation(StrictArtifactModel):
    signals: list[DriftSignal]
    missingness: list[MissingnessSignal]


def smooth_proportions(values: Sequence[float], *, epsilon: float = 1e-6) -> np.ndarray:
    """Apply ``(p_i + epsilon) / (1 + k*epsilon)`` to one probability vector."""

    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) == 0:
        raise ValueError("probability vector must be one-dimensional and non-empty")
    if not np.isfinite(vector).all() or (vector < 0.0).any():
        raise ValueError("probabilities must be finite and non-negative")
    if not math.isfinite(epsilon) or not 0.0 < epsilon < 1.0:
        raise ValueError("epsilon must be finite in (0, 1)")
    if not math.isclose(float(vector.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("probability vector must sum to one")
    return (vector + epsilon) / (1.0 + len(vector) * epsilon)


def population_stability_index(
    baseline: Sequence[float],
    current: Sequence[float],
    *,
    epsilon: float = 1e-6,
) -> float:
    """Compute natural-log PSI over equally sized smoothed vectors."""

    if len(baseline) != len(current):
        raise ValueError("PSI vectors must have equal length")
    baseline_smoothed = smooth_proportions(baseline, epsilon=epsilon)
    current_smoothed = smooth_proportions(current, epsilon=epsilon)
    value = np.sum(
        (current_smoothed - baseline_smoothed) * np.log(current_smoothed / baseline_smoothed)
    )
    return max(float(value), 0.0)


def jensen_shannon_distance(
    baseline: Sequence[float],
    current: Sequence[float],
    *,
    epsilon: float = 1e-6,
) -> float:
    """Compute square-root base-2 Jensen-Shannon divergence in ``[0, 1]``."""

    if len(baseline) != len(current):
        raise ValueError("JS vectors must have equal length")
    baseline_smoothed = smooth_proportions(baseline, epsilon=epsilon)
    current_smoothed = smooth_proportions(current, epsilon=epsilon)
    midpoint = (baseline_smoothed + current_smoothed) / 2.0
    divergence = 0.5 * float(
        np.sum(baseline_smoothed * np.log2(baseline_smoothed / midpoint))
        + np.sum(current_smoothed * np.log2(current_smoothed / midpoint))
    )
    return min(max(math.sqrt(max(divergence, 0.0)), 0.0), 1.0)


def _proportions_from_counts(counts: Sequence[int]) -> list[float]:
    if any(count < 0 for count in counts):
        raise ValueError("bin counts cannot be negative")
    total = sum(counts)
    if total == 0:
        raise ValueError("an empty count vector is unevaluable")
    return [count / total for count in counts]


def metric_severity(value: float, *, warning: float, degraded: float) -> DriftState:
    if value >= degraded:
        return DriftState.DEGRADED
    if value >= warning:
        return DriftState.WARNING
    return DriftState.HEALTHY


def evaluate_distribution_signal(
    *,
    name: str,
    kind: Literal[
        "numeric_psi", "categorical_js_distance", "prediction_psi", "decision_js_distance"
    ],
    baseline: list[float],
    current_counts: list[int],
    universe: list[str],
    config: MonitoringConfig,
    constant: bool,
) -> DriftSignal:
    if not current_counts or sum(current_counts) == 0:
        return DriftSignal(
            name=name,
            kind=kind,
            value=None,
            state=DriftState.UNKNOWN,
            reason="empty_or_unevaluable_input",
            baseline_proportions=baseline,
            current_proportions=[],
            universe=universe,
        )
    current = _proportions_from_counts(current_counts)
    if constant:
        positive_baseline = [index for index, value in enumerate(baseline) if value > 0.0]
        unchanged = len(positive_baseline) == 1 and current_counts[positive_baseline[0]] == sum(
            current_counts
        )
        return DriftSignal(
            name=name,
            kind=kind,
            value=None,
            state=DriftState.HEALTHY if unchanged else DriftState.DEGRADED,
            reason=("constant_baseline_unchanged" if unchanged else "constant_baseline_changed"),
            baseline_proportions=baseline,
            current_proportions=current,
            universe=universe,
        )
    try:
        if kind in {"numeric_psi", "prediction_psi"}:
            value = population_stability_index(baseline, current, epsilon=config.smoothing_epsilon)
            state = metric_severity(
                value,
                warning=config.psi_warning_threshold,
                degraded=config.psi_degraded_threshold,
            )
        else:
            value = jensen_shannon_distance(baseline, current, epsilon=config.smoothing_epsilon)
            state = metric_severity(
                value,
                warning=config.js_warning_threshold,
                degraded=config.js_degraded_threshold,
            )
    except ValueError:
        return DriftSignal(
            name=name,
            kind=kind,
            value=None,
            state=DriftState.UNKNOWN,
            reason="empty_or_unevaluable_input",
            baseline_proportions=baseline,
            current_proportions=current,
            universe=universe,
        )
    return DriftSignal(
        name=name,
        kind=kind,
        value=value,
        state=state,
        reason="metric_evaluated",
        baseline_proportions=baseline,
        current_proportions=current,
        universe=universe,
    )


def _numeric_counts(values: Sequence[object], profile: NumericFeatureProfile) -> list[int] | None:
    finite: list[float] = []
    for raw_value in values:
        if raw_value is None:
            continue
        if not isinstance(raw_value, (bool, int, float)):
            return None
        value = float(raw_value)
        if not math.isfinite(value):
            return None
        finite.append(value)
    if not finite:
        return []
    edges = profile.collapsed_reference_edges
    minimum = edges[0]
    maximum = edges[-1]
    counts = [sum(value < minimum for value in finite)]
    if len(edges) == 1:
        counts.append(sum(value == minimum for value in finite))
    else:
        for index, (lower, upper) in enumerate(pairwise(edges)):
            if index == len(edges) - 2:
                counts.append(sum(lower <= value <= upper for value in finite))
            else:
                counts.append(sum(lower <= value < upper for value in finite))
    counts.append(sum(value > maximum for value in finite))
    if sum(counts) != len(finite):
        raise ValueError("numeric values did not reconcile to frozen bins")
    return counts


def evaluate_missingness_signal(
    feature: str,
    values: Sequence[object],
    baseline_rate: float,
    config: MonitoringConfig,
) -> MissingnessSignal:
    current_rate = sum(value is None for value in values) / len(values) if values else 0.0
    delta = abs(current_rate - baseline_rate)
    state: Literal["valid", "warning", "invalid"]
    if delta >= config.missingness_invalid_threshold:
        state = "invalid"
    elif delta >= config.missingness_warning_threshold:
        state = "warning"
    else:
        state = "valid"
    return MissingnessSignal(
        feature=feature,
        baseline_rate=baseline_rate,
        current_rate=current_rate,
        absolute_delta=delta,
        state=state,
    )


def evaluate_drift(
    events: Sequence[PredictionEventV1],
    baseline: BaselineProfile,
    config: MonitoringConfig,
) -> DriftEvaluation:
    """Evaluate every required frozen feature, score, decision, and missingness signal."""

    signals: list[DriftSignal] = []
    missingness: list[MissingnessSignal] = []
    for name in config.required_numeric_features:
        numeric_profile = baseline.numeric_features[name]
        values = [getattr(event.features, name) for event in events]
        current_counts = _numeric_counts(values, numeric_profile)
        baseline_values = [float(item.proportion.value or 0.0) for item in numeric_profile.bins]
        if current_counts is None:
            signal = DriftSignal(
                name=name,
                kind="numeric_psi",
                value=None,
                state=DriftState.UNKNOWN,
                reason="non_finite_current_value",
                baseline_proportions=baseline_values,
                current_proportions=[],
                universe=[item.semantic for item in numeric_profile.bins],
            )
        else:
            signal = evaluate_distribution_signal(
                name=name,
                kind="numeric_psi",
                baseline=baseline_values,
                current_counts=current_counts,
                universe=[item.semantic for item in numeric_profile.bins],
                config=config,
                constant=numeric_profile.constant,
            )
        signals.append(signal)
        baseline_missingness = float(numeric_profile.missingness.proportion.value or 0.0)
        missingness.append(evaluate_missingness_signal(name, values, baseline_missingness, config))

    for name in config.required_categorical_features:
        categorical_profile = baseline.categorical_features[name]
        values = [getattr(event.features, name) for event in events]
        counts = dict.fromkeys(categorical_profile.universe, 0)
        for value in values:
            bucket: str
            if value is None:
                bucket = config.missing_bucket
            elif str(value) in counts and str(value) not in {
                config.other_bucket,
                config.missing_bucket,
            }:
                bucket = str(value)
            else:
                bucket = config.other_bucket
            counts[bucket] += 1
        baseline_values = [
            float(categorical_profile.proportions[key].value or 0.0)
            for key in categorical_profile.universe
        ]
        signals.append(
            evaluate_distribution_signal(
                name=name,
                kind="categorical_js_distance",
                baseline=baseline_values,
                current_counts=[counts[key] for key in categorical_profile.universe],
                universe=categorical_profile.universe,
                config=config,
                constant=categorical_profile.constant,
            )
        )
        baseline_missingness = float(categorical_profile.missingness.proportion.value or 0.0)
        missingness.append(evaluate_missingness_signal(name, values, baseline_missingness, config))

    score_profile = baseline.calibrated_score_distribution
    score_counts = [0] * len(score_profile.bins)
    scores_evaluable = True
    for event in events:
        score = float(event.score)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            scores_evaluable = False
            break
        index = min(int(score * 10), 9)
        score_counts[index] += 1
    score_baseline = [float(item.proportion.value or 0.0) for item in score_profile.bins]
    if scores_evaluable:
        signals.append(
            evaluate_distribution_signal(
                name="prediction_score",
                kind="prediction_psi",
                baseline=score_baseline,
                current_counts=score_counts,
                universe=[item.interval for item in score_profile.bins],
                config=config,
                constant=sum(value > 0.0 for value in score_baseline) == 1,
            )
        )
    else:
        signals.append(
            DriftSignal(
                name="prediction_score",
                kind="prediction_psi",
                state=DriftState.UNKNOWN,
                reason="non_finite_current_value",
                baseline_proportions=score_baseline,
                current_proportions=[],
                universe=[item.interval for item in score_profile.bins],
            )
        )

    decision_universe = ["low_risk", "high_risk", config.other_bucket, config.missing_bucket]
    decision_counts: dict[str, int] = dict.fromkeys(decision_universe, 0)
    for event in events:
        decision_counts[event.decision.value] += 1
    decision_baseline = [
        float(baseline.locked_decision_distribution.proportions[key].value or 0.0)
        if key in baseline.locked_decision_distribution.proportions
        else 0.0
        for key in decision_universe
    ]
    signals.append(
        evaluate_distribution_signal(
            name="locked_decision",
            kind="decision_js_distance",
            baseline=decision_baseline,
            current_counts=[decision_counts[key] for key in decision_universe],
            universe=decision_universe,
            config=config,
            constant=sum(value > 0.0 for value in decision_baseline) == 1,
        )
    )
    return DriftEvaluation(signals=signals, missingness=missingness)


def categorical_counts(
    values: Sequence[object],
    universe: Sequence[str],
    *,
    other_bucket: str = "__OTHER__",
    missing_bucket: str = "__MISSING__",
) -> Mapping[str, int]:
    """Public small helper used by reference-vector and special-bucket tests."""

    counts = dict.fromkeys(universe, 0)
    if other_bucket not in counts or missing_bucket not in counts:
        raise ValueError("categorical universe requires __OTHER__ and __MISSING__")
    for value in values:
        bucket = missing_bucket if value is None else str(value)
        if bucket not in counts:
            bucket = other_bucket
        counts[bucket] += 1
    return counts
