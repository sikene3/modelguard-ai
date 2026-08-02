"""Strict delayed-label schema, join, adequacy, metrics, and cost-policy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from modelguard.core.serialization import canonical_json_bytes
from modelguard.monitoring.config import PERFORMANCE_SCOPE_WORDING, MonitoringConfig
from modelguard.monitoring.events import freeze_raw_payloads
from modelguard.monitoring.performance import DelayedLabelV1, evaluate_delayed_performance
from modelguard.monitoring.state import PerformanceState

EVENT_TIME = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
LABEL_TIME = datetime(2026, 1, 1, 2, tzinfo=UTC)


def _events(factory: Any, count: int = 500) -> tuple[object, ...]:
    return tuple(factory(index, EVENT_TIME, score=0.5) for index in range(count))


def _label(event: object, value: int, *, labeled_at: datetime = LABEL_TIME) -> DelayedLabelV1:
    return DelayedLabelV1(
        label_schema_version="modelguard.label.v1",
        event_id=event.event_id,
        label=value,
        labeled_at=labeled_at,
    )


def _snapshot(labels: list[object]) -> object:
    return freeze_raw_payloads([b"".join(canonical_json_bytes(label) + b"\n" for label in labels)])


def test_minimal_label_schema_is_strict_binary_utc_and_extra_forbidding() -> None:
    valid = {
        "label_schema_version": "modelguard.label.v1",
        "event_id": str(UUID(int=1)),
        "label": 1,
        "labeled_at": "2026-01-01T02:00:00Z",
    }
    assert DelayedLabelV1.model_validate_json(canonical_json_bytes(valid)).label == 1
    for changed in (
        {**valid, "label": 2},
        {**valid, "label": True},
        {**valid, "labeled_at": "2026-01-01T04:00:00+02:00"},
        {**valid, "unexpected": "forbidden"},
    ):
        with pytest.raises(ValidationError):
            DelayedLabelV1.model_validate_json(canonical_json_bytes(changed))


def test_no_label_source_is_unknown_and_never_inferred_from_drift(
    monitoring_event_factory: Any,
) -> None:
    events = _events(monitoring_event_factory)
    result = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=None,
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation

    assert result.state is PerformanceState.UNKNOWN
    assert result.reason == "no_label_source_configured"
    assert result.metrics is None
    assert result.interpretation == PERFORMANCE_SCOPE_WORDING
    assert "selection bias" in result.limitation


def test_configured_labels_report_coverage_missing_orphans_and_pending_adequacy(
    monitoring_event_factory: Any,
) -> None:
    events = _events(monitoring_event_factory)
    labels = [_label(event, index % 2) for index, event in enumerate(events[:400])]
    orphan_event = monitoring_event_factory(999, EVENT_TIME, score=0.5)
    labels.append(_label(orphan_event, 0))
    result = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=_snapshot(labels),  # type: ignore[arg-type]
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation

    assert result.state is PerformanceState.PENDING_LABELS
    assert result.coverage == pytest.approx(0.80)
    assert result.counts.joined == 400
    assert result.counts.orphan == 1
    assert result.counts.missing == 100
    assert result.metrics is None


def test_label_adequacy_accepts_exact_coverage_row_and_negative_boundaries(
    monitoring_event_factory: Any,
) -> None:
    events = _events(monitoring_event_factory, count=625)
    # Five hundred joined rows are exactly 80% coverage. The label split has exactly 100
    # negatives and 400 positives, so every default adequacy boundary is met.
    labels = [_label(event, 0 if index < 100 else 1) for index, event in enumerate(events[:500])]
    exact = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=_snapshot(labels),  # type: ignore[arg-type]
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation
    below_coverage = evaluate_delayed_performance(
        (*events, monitoring_event_factory(626, EVENT_TIME, score=0.5)),  # type: ignore[arg-type]
        label_snapshot=_snapshot(labels),  # type: ignore[arg-type]
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation

    assert exact.coverage == 0.80
    assert exact.counts.joined == 500
    assert exact.counts.negative_joined == 100
    assert exact.metrics is not None
    assert below_coverage.coverage is not None and below_coverage.coverage < 0.80
    assert below_coverage.state is PerformanceState.PENDING_LABELS
    assert below_coverage.metrics is None


def test_identical_labels_deduplicate_but_conflicts_make_performance_unknown(
    monitoring_event_factory: Any,
) -> None:
    events = _events(monitoring_event_factory)
    first = _label(events[0], 0)
    benign = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=_snapshot([first, first]),  # type: ignore[arg-type]
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation
    conflicting = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=_snapshot([first, _label(events[0], 1)]),  # type: ignore[arg-type]
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation

    assert benign.state is PerformanceState.PENDING_LABELS
    assert benign.counts.duplicate == 1
    assert benign.counts.joined == 1
    assert conflicting.state is PerformanceState.UNKNOWN
    assert conflicting.reason == "conflicting_label_group"
    assert conflicting.counts.conflicting == 2


def test_unknown_and_malformed_label_schemas_are_unknown(
    monitoring_event_factory: Any,
) -> None:
    events = _events(monitoring_event_factory)
    base = {
        "label_schema_version": "modelguard.label.v9",
        "event_id": str(events[0].event_id),
        "label": 0,
        "labeled_at": "2026-01-01T02:00:00Z",
    }
    unknown = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=freeze_raw_payloads([canonical_json_bytes(base) + b"\n"]),
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation
    malformed_payload = {**base, "label_schema_version": "modelguard.label.v1"}
    malformed_payload.pop("label")
    malformed = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=freeze_raw_payloads([canonical_json_bytes(malformed_payload)]),
        locked_threshold=0.075,
        held_out_reference_cost_per_event=0.75,
        config=MonitoringConfig(),
    ).evaluation

    assert unknown.state is PerformanceState.UNKNOWN
    assert unknown.reason == "unknown_label_schema_version"
    assert unknown.counts.unknown_schema_version == 1
    assert malformed.state is PerformanceState.UNKNOWN
    assert malformed.reason == "invalid_label_schema"


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (0.860001, PerformanceState.HEALTHY),
        (0.86, PerformanceState.WARNING),
        (0.710001, PerformanceState.WARNING),
        (0.71, PerformanceState.DEGRADED),
    ],
)
def test_adequate_labels_compute_only_label_backed_metrics_and_cost_boundaries(
    monitoring_event_factory: Any,
    reference: float,
    expected: PerformanceState,
) -> None:
    events = _events(monitoring_event_factory)
    # Every score is above the locked threshold. Twenty positives and 480 negatives therefore
    # produce FP=480, FN=0, synthetic cost/event=.96 with both classes adequate.
    labels = [_label(event, 1 if index < 20 else 0) for index, event in enumerate(events)]
    result = evaluate_delayed_performance(
        events,  # type: ignore[arg-type]
        label_snapshot=_snapshot(labels),  # type: ignore[arg-type]
        locked_threshold=0.075,
        held_out_reference_cost_per_event=reference,
        config=MonitoringConfig(),
    ).evaluation

    assert result.state is expected
    assert result.coverage == 1.0
    assert result.counts.positive_joined == 20
    assert result.counts.negative_joined == 480
    assert result.metrics is not None
    assert result.metrics.synthetic_cost == 480
    assert result.metrics.synthetic_cost_per_event == pytest.approx(0.96)
    assert result.metrics.synthetic_cost_delta == pytest.approx(0.96 - reference)
    assert 0.0 <= result.metrics.average_precision <= 1.0
    assert 0.0 <= result.metrics.roc_auc <= 1.0
    assert "accuracy" not in result.metrics.model_dump()
