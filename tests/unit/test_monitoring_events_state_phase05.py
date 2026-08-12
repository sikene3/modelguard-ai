"""Window, snapshot, identity, reconciliation, deduplication, and state tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from modelguard.core.serialization import canonical_json_bytes
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.events import (
    EventIdentity,
    classify_snapshot,
    default_window_end,
    freeze_local_raw_snapshot,
    freeze_raw_payloads,
    parse_strict_json_record,
    parse_utc_timestamp,
    resolve_window,
)
from modelguard.monitoring.state import (
    DataQualityState,
    DriftState,
    PerformanceState,
    RunState,
    aggregate_drift_state,
    assess_data_quality,
    determine_run_state,
    performance_state_from_delta,
)

WINDOW_END = datetime(2026, 1, 1, 1, tzinfo=UTC)


def _line(event: object) -> bytes:
    return canonical_json_bytes(event) + b"\n"


def test_window_is_utc_half_open_and_grace_boundary_is_inclusive() -> None:
    config = MonitoringConfig()
    with pytest.raises(ValueError, match="finalization grace"):
        resolve_window(
            as_of=WINDOW_END + timedelta(minutes=9, seconds=59),
            window_end=WINDOW_END,
            config=config,
        )
    window = resolve_window(
        as_of=WINDOW_END + timedelta(minutes=10),
        window_end=WINDOW_END,
        config=config,
    )
    assert window.start == WINDOW_END - timedelta(hours=1)
    assert window.end == WINDOW_END
    assert window.eligible_at == WINDOW_END + timedelta(minutes=10)
    assert window.delivery_lateness_metric == "not_claimed"


def test_default_window_uses_latest_whole_hour_after_grace_without_hidden_clock() -> None:
    config = MonitoringConfig()
    as_of = datetime(2026, 1, 1, 1, 37, tzinfo=UTC)
    assert default_window_end(as_of, config) == datetime(2026, 1, 1, 1, tzinfo=UTC)
    assert resolve_window(as_of=as_of, config=config).duration_seconds == 3_600
    assert parse_utc_timestamp("2026-01-01T01:00:00Z", name="test") == WINDOW_END
    with pytest.raises(ValueError, match="ending in Z"):
        parse_utc_timestamp("2026-01-01T03:00:00+02:00", name="test")


def test_half_open_timestamp_edges_classify_start_in_and_end_out(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
) -> None:
    window = resolve_window(
        as_of=WINDOW_END + timedelta(minutes=10),
        window_end=WINDOW_END,
        config=MonitoringConfig(),
    )
    at_start = monitoring_event_factory(1, window.start)
    at_end = monitoring_event_factory(2, window.end)
    result = classify_snapshot(
        freeze_raw_payloads([_line(at_start) + _line(at_end)]),
        window=window,
        target=monitoring_target,
    )
    assert result.summary.counts.model_dump() == {
        "raw": 2,
        "rejected": 0,
        "outside_window": 1,
        "known_non_target": 0,
        "duplicate": 0,
        "accepted_target": 1,
    }


def test_frozen_local_snapshot_excludes_open_files_and_survives_later_append(
    tmp_path: Path,
    monitoring_event_factory: Any,
) -> None:
    closed = tmp_path / "closed.jsonl"
    active = tmp_path / "active.jsonl.open"
    first = _line(monitoring_event_factory(1, WINDOW_END - timedelta(minutes=30)))
    second = _line(monitoring_event_factory(2, WINDOW_END - timedelta(minutes=20)))
    closed.write_bytes(first)
    active.write_bytes(second)

    frozen = freeze_local_raw_snapshot(tmp_path)
    with closed.open("ab") as handle:
        handle.write(second)

    assert frozen.records == (first.rstrip(b"\n"),)
    assert freeze_local_raw_snapshot(tmp_path).records == (
        first.rstrip(b"\n"),
        second.rstrip(b"\n"),
    )


def test_local_snapshot_normalizes_invalid_deflate_and_excessive_json_nesting(
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "corrupt.jsonl.gz"
    corrupt.write_bytes(b"\x1f\x8b\x08\x00" + b"x" * 30)

    with pytest.raises(RuntimeError, match="could not freeze an input object"):
        freeze_local_raw_snapshot(tmp_path)
    with pytest.raises(ValueError, match="bounded nesting contract"):
        parse_strict_json_record(b"[" * 1_200 + b"0" + b"]" * 1_200)


def test_snapshot_identity_ignores_order_repartition_and_enclosing_file_append(
    monitoring_event_factory: Any,
) -> None:
    lines = [
        _line(monitoring_event_factory(index, WINDOW_END - timedelta(minutes=30)))
        for index in range(3)
    ]
    single = freeze_raw_payloads([b"".join(lines)])
    repartitioned = freeze_raw_payloads([lines[2], lines[0] + lines[1]])
    unrelated_append = freeze_raw_payloads([b"".join(lines), b""])

    assert single.digest == repartitioned.digest == unrelated_append.digest
    assert sorted(single.record_digests) == sorted(repartitioned.record_digests)


def test_exclusive_classification_reconciles_all_classes_and_is_order_independent(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
) -> None:
    known = EventIdentity(
        event_schema_version="modelguard.prediction-event.v1",
        model_version="2.0.0",
        bundle_manifest_sha256="b" * 64,
        input_schema_version="modelguard.input.v1",
    )
    unknown = known.model_copy(
        update={"model_version": "9.0.0", "bundle_manifest_sha256": "c" * 64}
    )
    conflicting_identity = monitoring_target.model_copy(update={"bundle_manifest_sha256": "d" * 64})
    inside = WINDOW_END - timedelta(minutes=30)
    identical = monitoring_event_factory(10, inside)
    accepted = monitoring_event_factory(11, inside)
    conflict_id = UUID(int=999)
    conflict_a = monitoring_event_factory(12, inside, event_id=conflict_id, score=0.2)
    conflict_b = monitoring_event_factory(13, inside, event_id=conflict_id, score=0.8)
    records = [
        b"{not-json}\n",
        _line(monitoring_event_factory(1, WINDOW_END)),
        _line(monitoring_event_factory(2, inside, identity=known)),
        _line(identical),
        _line(identical),
        _line(accepted),
        _line(conflict_a),
        _line(conflict_b),
        _line(monitoring_event_factory(14, inside, identity=unknown)),
        _line(monitoring_event_factory(15, inside, identity=conflicting_identity)),
    ]
    window = resolve_window(
        as_of=WINDOW_END + timedelta(minutes=10),
        window_end=WINDOW_END,
        config=MonitoringConfig(),
    )
    forward = classify_snapshot(
        freeze_raw_payloads(records),
        window=window,
        target=monitoring_target,
        known_non_targets=[known],
    )
    reverse = classify_snapshot(
        freeze_raw_payloads(list(reversed(records))),
        window=window,
        target=monitoring_target,
        known_non_targets=[known],
    )

    assert forward.summary.counts.model_dump() == {
        "raw": 10,
        "rejected": 5,
        "outside_window": 1,
        "known_non_target": 1,
        "duplicate": 1,
        "accepted_target": 2,
    }
    assert forward.summary.faults.model_dump() == {
        "parse_or_schema_failures": 1,
        "unknown_identity_records": 1,
        "conflicting_identity_records": 1,
        "conflicting_event_id_groups": 1,
        "conflicting_event_id_records": 2,
    }
    assert forward.classified_record_digests == reverse.classified_record_digests
    assert [event.event_id for event in forward.accepted_events] == [
        event.event_id for event in reverse.accepted_events
    ]


def test_schema_failure_does_not_advance_to_identity_classification(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
) -> None:
    unknown = EventIdentity(
        event_schema_version="modelguard.prediction-event.v1",
        model_version="9.0.0",
        bundle_manifest_sha256="c" * 64,
        input_schema_version="modelguard.input.v1",
    )
    malformed = monitoring_event_factory(
        1,
        WINDOW_END - timedelta(minutes=30),
        identity=unknown,
    ).model_dump(mode="json")
    malformed.pop("score")
    window = resolve_window(
        as_of=WINDOW_END + timedelta(minutes=10),
        window_end=WINDOW_END,
        config=MonitoringConfig(),
    )

    result = classify_snapshot(
        freeze_raw_payloads([canonical_json_bytes(malformed) + b"\n"]),
        window=window,
        target=monitoring_target,
    )

    assert result.summary.counts.rejected == 1
    assert result.summary.faults.parse_or_schema_failures == 1
    assert result.summary.faults.unknown_identity_records == 0
    assert result.summary.faults.conflicting_identity_records == 0
    assert result.summary.observed_event_carried_identities == []


def test_outside_window_record_does_not_advance_to_identity_classification(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
) -> None:
    unknown = EventIdentity(
        event_schema_version="modelguard.prediction-event.v1",
        model_version="9.0.0",
        bundle_manifest_sha256="c" * 64,
        input_schema_version="modelguard.input.v1",
    )
    outside = monitoring_event_factory(1, WINDOW_END, identity=unknown)
    window = resolve_window(
        as_of=WINDOW_END + timedelta(minutes=10),
        window_end=WINDOW_END,
        config=MonitoringConfig(),
    )

    result = classify_snapshot(
        freeze_raw_payloads([_line(outside)]),
        window=window,
        target=monitoring_target,
    )

    assert result.summary.counts.outside_window == 1
    assert result.summary.counts.rejected == 0
    assert result.summary.faults.unknown_identity_records == 0
    assert result.summary.faults.conflicting_identity_records == 0
    assert result.summary.observed_event_carried_identities == []


def _quality(**updates: object) -> DataQualityState:
    values: dict[str, object] = {
        "raw_count": 500,
        "rejected_count": 0,
        "accepted_target_count": 500,
        "duplicate_count": 0,
        "known_non_target_count": 0,
        "minimum_accepted_events": 500,
        "maximum_missingness_delta": 0.0,
        "reconciliation_valid": True,
        "bundle_valid": True,
        "identity_fault": False,
        "conflicting_event_id_fault": False,
        "config": MonitoringConfig(),
    }
    values.update(updates)
    return assess_data_quality(**values).state  # type: ignore[arg-type]


def test_data_quality_precedence_and_exact_rejection_boundary() -> None:
    assert _quality() is DataQualityState.VALID
    # The extra raw row represents outside-window traffic, which alone does not warn.
    assert _quality(raw_count=501) is DataQualityState.VALID
    assert (
        _quality(accepted_target_count=499, duplicate_count=1) is DataQualityState.INSUFFICIENT_DATA
    )
    assert _quality(duplicate_count=1) is DataQualityState.WARNING
    assert _quality(known_non_target_count=1) is DataQualityState.WARNING
    assert _quality(raw_count=1_000, rejected_count=49) is DataQualityState.WARNING
    assert _quality(raw_count=1_000, rejected_count=50) is DataQualityState.INVALID
    assert _quality(maximum_missingness_delta=0.05) is DataQualityState.INVALID
    assert _quality(identity_fault=True, accepted_target_count=1) is DataQualityState.INVALID
    assert _quality(reconciliation_valid=False) is DataQualityState.INVALID


def test_run_drift_and_performance_state_precedence_and_boundaries() -> None:
    as_of = datetime(2026, 1, 1, 4, tzinfo=UTC)
    assert (
        determine_run_state(
            current_attempt_failed=True,
            latest_success_at=None,
            as_of=as_of,
            stale_after=timedelta(hours=2),
        )
        is RunState.FAILED
    )
    assert (
        determine_run_state(
            current_attempt_failed=False,
            latest_success_at=None,
            as_of=as_of,
            stale_after=timedelta(hours=2),
        )
        is RunState.NEVER_RUN
    )
    assert (
        determine_run_state(
            current_attempt_failed=False,
            latest_success_at=as_of - timedelta(hours=2),
            as_of=as_of,
            stale_after=timedelta(hours=2),
        )
        is RunState.STALE
    )
    assert (
        aggregate_drift_state(
            [DriftState.HEALTHY], data_quality_state=DataQualityState.INSUFFICIENT_DATA
        )
        is DriftState.UNKNOWN
    )
    assert (
        aggregate_drift_state(
            [DriftState.UNKNOWN, DriftState.DEGRADED], data_quality_state=DataQualityState.WARNING
        )
        is DriftState.DEGRADED
    )
    config = MonitoringConfig()
    assert performance_state_from_delta(0.09999999, config) is PerformanceState.HEALTHY
    assert performance_state_from_delta(0.10, config) is PerformanceState.WARNING
    assert performance_state_from_delta(0.24999999, config) is PerformanceState.WARNING
    assert performance_state_from_delta(0.25, config) is PerformanceState.DEGRADED
