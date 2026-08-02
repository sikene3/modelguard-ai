"""Reference-vector and edge tests for the transparent Phase 05 drift core."""

from __future__ import annotations

import math

import numpy as np
import pytest

from modelguard.monitoring.config import MonitoringConfig, monitoring_config_hash
from modelguard.monitoring.drift import (
    categorical_counts,
    evaluate_distribution_signal,
    evaluate_missingness_signal,
    jensen_shannon_distance,
    metric_severity,
    population_stability_index,
    smooth_proportions,
)
from modelguard.monitoring.state import DriftState


def _reference_smooth(values: list[float], epsilon: float = 1e-6) -> list[float]:
    return [(value + epsilon) / (1 + len(values) * epsilon) for value in values]


def test_psi_matches_known_natural_log_reference_vector_and_zero_bins() -> None:
    baseline = [0.5, 0.5, 0.0]
    current = [0.6, 0.3, 0.1]
    expected_baseline = _reference_smooth(baseline)
    expected_current = _reference_smooth(current)
    expected = sum(
        (current_value - baseline_value) * math.log(current_value / baseline_value)
        for baseline_value, current_value in zip(expected_baseline, expected_current, strict=True)
    )

    assert population_stability_index(baseline, current) == pytest.approx(expected, abs=1e-15)
    assert population_stability_index(baseline, baseline) == pytest.approx(0.0, abs=1e-15)
    assert population_stability_index([1.0, 0.0], [0.0, 1.0]) > 20.0


def test_js_distance_matches_base2_reference_and_identity_symmetry_bounds() -> None:
    baseline = [0.5, 0.5]
    current = [0.75, 0.25]
    left = _reference_smooth(baseline)
    right = _reference_smooth(current)
    midpoint = [(a + b) / 2 for a, b in zip(left, right, strict=True)]
    divergence = 0.5 * sum(
        value * math.log2(value / middle) for value, middle in zip(left, midpoint, strict=True)
    ) + 0.5 * sum(
        value * math.log2(value / middle) for value, middle in zip(right, midpoint, strict=True)
    )
    expected = math.sqrt(divergence)

    assert jensen_shannon_distance(baseline, current) == pytest.approx(expected, abs=1e-15)
    assert jensen_shannon_distance(current, baseline) == pytest.approx(expected, abs=1e-15)
    assert jensen_shannon_distance(baseline, baseline) == pytest.approx(0.0, abs=1e-15)
    assert 0.0 <= jensen_shannon_distance([1.0, 0.0], [0.0, 1.0]) <= 1.0


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ([], "non-empty"),
        ([0.0, 0.0], "sum to one"),
        ([math.nan, 0.0], "finite"),
        ([math.inf, 0.0], "finite"),
        ([-0.1, 1.1], "non-negative"),
    ],
)
def test_smoothing_rejects_empty_non_finite_and_invalid_vectors(
    values: list[float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        smooth_proportions(values)


def test_smoothing_uses_the_exact_versioned_formula_and_renormalizes() -> None:
    actual = smooth_proportions([0.0, 0.25, 0.75])
    assert actual.tolist() == pytest.approx(_reference_smooth([0.0, 0.25, 0.75]))
    assert float(actual.sum()) == pytest.approx(1.0, abs=1e-15)
    with pytest.raises(ValueError, match="equal length"):
        population_stability_index([1.0], [0.5, 0.5])
    with pytest.raises(ValueError, match="equal length"):
        jensen_shannon_distance([1.0], [0.5, 0.5])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.099999999, DriftState.HEALTHY),
        (0.10, DriftState.WARNING),
        (0.249999999, DriftState.WARNING),
        (0.25, DriftState.DEGRADED),
    ],
)
def test_metric_threshold_boundaries_are_inclusive(value: float, expected: DriftState) -> None:
    assert metric_severity(value, warning=0.10, degraded=0.25) is expected


def test_js_distance_uses_its_distinct_exact_degraded_boundary() -> None:
    assert metric_severity(0.099999999, warning=0.10, degraded=0.20) is DriftState.HEALTHY
    assert metric_severity(0.10, warning=0.10, degraded=0.20) is DriftState.WARNING
    assert metric_severity(0.199999999, warning=0.10, degraded=0.20) is DriftState.WARNING
    assert metric_severity(0.20, warning=0.10, degraded=0.20) is DriftState.DEGRADED


def test_constant_baseline_is_null_healthy_if_unchanged_and_null_degraded_if_changed() -> None:
    config = MonitoringConfig()
    unchanged = evaluate_distribution_signal(
        name="constant",
        kind="numeric_psi",
        baseline=[1.0, 0.0],
        current_counts=[10, 0],
        universe=["constant", "other"],
        config=config,
        constant=True,
    )
    changed = evaluate_distribution_signal(
        name="constant",
        kind="numeric_psi",
        baseline=[1.0, 0.0],
        current_counts=[9, 1],
        universe=["constant", "other"],
        config=config,
        constant=True,
    )
    empty = evaluate_distribution_signal(
        name="constant",
        kind="numeric_psi",
        baseline=[1.0, 0.0],
        current_counts=[0, 0],
        universe=["constant", "other"],
        config=config,
        constant=True,
    )

    assert (unchanged.value, unchanged.state, unchanged.reason) == (
        None,
        DriftState.HEALTHY,
        "constant_baseline_unchanged",
    )
    assert (changed.value, changed.state, changed.reason) == (
        None,
        DriftState.DEGRADED,
        "constant_baseline_changed",
    )
    assert empty.state is DriftState.UNKNOWN


@pytest.mark.parametrize(
    ("missing_count", "expected"),
    [(1, "valid"), (2, "warning"), (4, "warning"), (5, "invalid")],
)
def test_missingness_exact_warning_and_invalid_boundaries(
    missing_count: int, expected: str
) -> None:
    values: list[object] = [None] * missing_count + [1.0] * (100 - missing_count)
    signal = evaluate_missingness_signal(
        "amount", values, baseline_rate=0.0, config=MonitoringConfig()
    )
    assert signal.absolute_delta == pytest.approx(missing_count / 100)
    assert signal.state == expected


def test_categorical_special_buckets_are_complete_and_deterministic() -> None:
    counts = categorical_counts(
        ["US", "EG", "unexpected", None],
        ["US", "EG", "__OTHER__", "__MISSING__"],
    )
    assert counts == {"US": 1, "EG": 1, "__OTHER__": 1, "__MISSING__": 1}
    with pytest.raises(ValueError, match="requires"):
        categorical_counts(["US"], ["US"])


def test_monitoring_configuration_hash_covers_result_policy_not_source_formatting() -> None:
    first = MonitoringConfig()
    second = MonitoringConfig.model_validate_json(first.model_dump_json())
    changed = first.model_copy(update={"minimum_accepted_events": 501})

    assert monitoring_config_hash(first) == monitoring_config_hash(second)
    assert monitoring_config_hash(first).digest != monitoring_config_hash(changed).digest
    assert np.isfinite(float(int(monitoring_config_hash(first).digest[:8], 16)))
