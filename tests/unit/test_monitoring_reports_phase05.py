"""Report identity, HTML, persistence, latest, alerts, EMF, and restart tests."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import pytest

from modelguard.core.config import AppEnvironment
from modelguard.core.hashing import sha256_bytes
from modelguard.core.serialization import canonical_json_bytes
from modelguard.monitoring.config import MonitoringConfig, monitoring_config_hash
from modelguard.monitoring.drift import evaluate_drift
from modelguard.monitoring.events import (
    EventIdentity,
    classify_snapshot,
    derive_baseline_identity,
    freeze_raw_payloads,
    resolve_window,
)
from modelguard.monitoring.performance import evaluate_delayed_performance
from modelguard.monitoring.persistence import (
    AlertNotification,
    AlertSendResult,
    AlertSendStatus,
    LocalReportStore,
    LocalRunStateStore,
)
from modelguard.monitoring.report import (
    MonitoringReport,
    build_monitoring_report,
    canonical_report_identity,
    render_offline_html,
)
from modelguard.monitoring.state import (
    DataQualityState,
    DriftState,
    PerformanceState,
    RunState,
    assess_data_quality,
)
from modelguard.monitoring.telemetry import build_monitor_completion_emf
from modelguard.training.bundle import ValidatedBundleMetadata


def _delayed_run_status_success(
    report_root: str,
    completed_at: str,
    report_id: str,
    ready_marker: str,
    release_marker: str,
) -> None:
    """Hold the first atomic replace so a competing process reaches the status update."""

    from modelguard.monitoring import persistence

    original_replace = persistence._atomic_replace

    def delayed_replace(path: Path, payload: bytes) -> None:
        Path(ready_marker).touch()
        deadline = time.monotonic() + 10
        while not Path(release_marker).exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("run-status interleaving release was not signaled")
            time.sleep(0.01)
        original_replace(path, payload)

    persistence._atomic_replace = delayed_replace
    persistence.LocalRunStateStore(Path(report_root)).record_success(
        completed_at=datetime.fromisoformat(completed_at),
        report_id=report_id,
    )


def _record_run_status_success(
    report_root: str,
    completed_at: str,
    report_id: str,
    started_marker: str,
    finished_marker: str,
) -> None:
    Path(started_marker).touch()
    LocalRunStateStore(Path(report_root)).record_success(
        completed_at=datetime.fromisoformat(completed_at),
        report_id=report_id,
    )
    Path(finished_marker).touch()


def _wait_for_marker(path: Path, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


WINDOW_END = datetime(2026, 1, 1, 1, tzinfo=UTC)


def _base_report(
    event_factory: Any,
    target: EventIdentity,
    metadata: ValidatedBundleMetadata,
) -> MonitoringReport:
    config = MonitoringConfig(minimum_accepted_events=1)
    window = resolve_window(
        as_of=WINDOW_END + timedelta(minutes=10),
        window_end=WINDOW_END,
        config=config,
    )
    event = event_factory(1, WINDOW_END - timedelta(minutes=30))
    classified = classify_snapshot(
        freeze_raw_payloads([canonical_json_bytes(event) + b"\n"]),
        window=window,
        target=target,
    )
    drift = evaluate_drift(classified.accepted_events, metadata.baseline, config)
    quality = assess_data_quality(
        raw_count=1,
        rejected_count=0,
        accepted_target_count=1,
        duplicate_count=0,
        known_non_target_count=0,
        minimum_accepted_events=1,
        maximum_missingness_delta=0.0,
        reconciliation_valid=True,
        bundle_valid=True,
        identity_fault=False,
        conflicting_event_id_fault=False,
        config=config,
    )
    performance = evaluate_delayed_performance(
        classified.accepted_events,
        label_snapshot=None,
        evaluation_cutoff=WINDOW_END + timedelta(minutes=10),
        locked_threshold=metadata.threshold.threshold,
        held_out_reference_cost_per_event=float(
            metadata.metrics.held_out_test.synthetic_cost_per_event.value or 0.0
        ),
        config=config,
    )
    return build_monitoring_report(
        window=window,
        target=target,
        baseline=derive_baseline_identity(metadata),
        config=config,
        config_hash=monitoring_config_hash(config),
        known_non_targets=[],
        classified=classified,
        quality=quality,
        drift_evaluation=drift,
        performance=performance,
    )


def _variant(
    report: MonitoringReport,
    *,
    hours: int,
    quality: DataQualityState = DataQualityState.VALID,
    drift: DriftState = DriftState.HEALTHY,
    performance: PerformanceState = PerformanceState.HEALTHY,
) -> MonitoringReport:
    data = report.model_dump(mode="python")
    end = report.window.end + timedelta(hours=hours)
    data["window"]["start"] = end - timedelta(seconds=report.window.duration_seconds)
    data["window"]["end"] = end
    data["window"]["eligible_at"] = end + timedelta(
        seconds=report.window.finalization_grace_seconds
    )
    data["states"].update({"data_quality": quality, "drift": drift, "performance": performance})
    data["data_quality"]["assessment"]["state"] = quality
    data["data_quality"]["assessment"]["reasons"] = ["test_variant"]
    data["drift"]["state"] = drift
    data["drift"]["reason"] = "test_variant"
    data["performance"]["state"] = performance
    data["performance"]["reason"] = "test_variant"
    data["performance"]["metrics"] = None
    digest = sha256_bytes(
        f"{report.report_id}:{hours}:{quality.value}:{drift.value}:{performance.value}".encode()
    )
    data["report_id"] = digest
    data["report_identity"]["hash"]["digest"] = digest
    return MonitoringReport.model_validate(data)


def test_canonical_report_id_is_order_independent_and_label_sensitive(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    base = _base_report(monitoring_event_factory, monitoring_target, monitoring_metadata)
    kwargs = {
        "window": base.window,
        "target": monitoring_target,
        "baseline": base.identities.baseline_derived_from_verified_manifest,
        "config_hash": base.identities.monitoring_config_hash,
    }
    first = canonical_report_identity(
        **kwargs,
        classified_record_digests=("accepted:a", "duplicate:b"),
        classified_label_digests=("joined:c", "orphan:d"),
    )
    reordered = canonical_report_identity(
        **kwargs,
        classified_record_digests=("duplicate:b", "accepted:a"),
        classified_label_digests=("orphan:d", "joined:c"),
    )
    changed_label = canonical_report_identity(
        **kwargs,
        classified_record_digests=("duplicate:b", "accepted:a"),
        classified_label_digests=("joined:changed", "orphan:d"),
    )
    configured_empty_labels = canonical_report_identity(
        **kwargs,
        classified_record_digests=("duplicate:b", "accepted:a"),
        classified_label_digests=("orphan:d", "joined:c"),
        label_source_configured=True,
        label_evaluation_cutoff=WINDOW_END + timedelta(minutes=10),
    )
    changed_cutoff = canonical_report_identity(
        **kwargs,
        classified_record_digests=("duplicate:b", "accepted:a"),
        classified_label_digests=("orphan:d", "joined:c"),
        label_source_configured=True,
        label_evaluation_cutoff=WINDOW_END + timedelta(minutes=11),
    )
    known_non_target = monitoring_target.model_copy(
        update={"model_version": "9.9.9", "bundle_manifest_sha256": "b" * 64}
    )
    changed_known_identities = canonical_report_identity(
        **kwargs,
        classified_record_digests=("duplicate:b", "accepted:a"),
        classified_label_digests=("orphan:d", "joined:c"),
        known_non_targets=[known_non_target],
    )
    assert first.hash.digest == reordered.hash.digest
    assert first.hash.digest != changed_label.hash.digest
    assert first.hash.digest != configured_empty_labels.hash.digest
    assert configured_empty_labels.hash.digest != changed_cutoff.hash.digest
    assert first.hash.digest != changed_known_identities.hash.digest
    assert "storage object name" in first.hash.exclusions


def test_strict_json_and_escaped_offline_html_have_no_external_dependency(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    report = _base_report(monitoring_event_factory, monitoring_target, monitoring_metadata)
    injected = report.model_copy(
        update={"limitations": [*report.limitations, '<script src="https://evil">x</script>']}
    )
    strict_json = canonical_json_bytes(report)
    assert json.loads(strict_json)["report_id"] == report.report_id
    assert b"NaN" not in strict_json and b"Infinity" not in strict_json

    html = render_offline_html(injected)
    assert '<script src="https://evil">' not in html
    assert "&lt;script src=&quot;https://evil&quot;&gt;x&lt;/script&gt;" in html
    assert "https://evil" in html  # escaped text, never a fetched resource
    assert "<script" not in html
    assert "synthetic-policy cost on the labeled subset" in html


def test_v1_reports_without_temporal_fields_remain_parseable_as_legacy(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    report = _base_report(monitoring_event_factory, monitoring_target, monitoring_metadata)
    legacy = report.model_dump(mode="json")
    legacy["performance"].pop("temporal_eligibility_policy")
    legacy["performance"].pop("evaluation_cutoff")
    legacy["performance"]["counts"].pop("temporally_ineligible")

    parsed = MonitoringReport.model_validate(legacy)
    assert parsed.performance.temporal_eligibility_policy == "not_recorded_legacy_v1"
    assert parsed.performance.evaluation_cutoff is None
    assert parsed.performance.counts.temporally_ineligible == 0


class RecordingAlertSink:
    def __init__(self) -> None:
        self.notifications: list[AlertNotification] = []
        self._lock = threading.Lock()

    def send(self, notification: AlertNotification) -> AlertSendResult:
        with self._lock:
            self.notifications.append(notification)
        return AlertSendResult(
            status=AlertSendStatus.SENT,
            provider_message_id=f"message-{len(self.notifications)}",
        )


def test_immutable_history_exact_rerun_monotonic_latest_and_restart_alert_dedupe(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    base = _base_report(monitoring_event_factory, monitoring_target, monitoring_metadata)
    healthy = _variant(base, hours=0)
    degraded = _variant(base, hours=1, drift=DriftState.DEGRADED)
    older = _variant(base, hours=-1, drift=DriftState.DEGRADED)
    sink = RecordingAlertSink()
    store = LocalReportStore(tmp_path)

    first = store.publish(healthy, alert_sink=sink)
    incident = store.publish(degraded, alert_sink=sink)
    repeated = LocalReportStore(tmp_path).publish(degraded, alert_sink=sink)
    old = store.publish(older, alert_sink=sink)

    assert first.latest_updated is True
    assert incident.latest_updated is True
    assert repeated.latest_updated is False
    assert repeated.json_sha256 == incident.json_sha256
    assert old.latest_updated is False
    assert store.read_latest() == degraded
    assert [item.dimension.value for item in sink.notifications] == ["drift"]
    marker = json.loads(incident.alert_markers[0].read_text())
    assert marker["claim_status"] == "claimed"
    assert marker["send_result"]["status"] == "sent"
    assert "does_not_guarantee_exactly_once" in marker["delivery_semantics"]


def test_concurrent_reentry_claims_one_alert_and_persists_across_restart(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    base = _base_report(monitoring_event_factory, monitoring_target, monitoring_metadata)
    store = LocalReportStore(tmp_path)
    store.publish(_variant(base, hours=0))
    store.publish(_variant(base, hours=1, drift=DriftState.DEGRADED))
    store.publish(_variant(base, hours=2, drift=DriftState.HEALTHY))
    reentry = _variant(base, hours=3, drift=DriftState.DEGRADED)
    sink = RecordingAlertSink()

    threads = [
        threading.Thread(
            target=lambda: LocalReportStore(tmp_path).publish(reentry, alert_sink=sink)
        )
        for _ in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(sink.notifications) == 1
    assert LocalReportStore(tmp_path).read_latest() == reentry
    LocalReportStore(tmp_path).publish(reentry, alert_sink=sink)
    assert len(sink.notifications) == 1


@pytest.mark.parametrize(
    ("quality", "drift", "performance", "expected_dimension"),
    [
        (
            DataQualityState.INVALID,
            DriftState.UNKNOWN,
            PerformanceState.UNKNOWN,
            "data_quality",
        ),
        (
            DataQualityState.VALID,
            DriftState.DEGRADED,
            PerformanceState.UNKNOWN,
            "drift",
        ),
        (
            DataQualityState.VALID,
            DriftState.HEALTHY,
            PerformanceState.DEGRADED,
            "performance",
        ),
    ],
)
def test_only_the_three_incident_entry_dimensions_claim_alerts(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
    quality: DataQualityState,
    drift: DriftState,
    performance: PerformanceState,
    expected_dimension: str,
) -> None:
    base = _base_report(monitoring_event_factory, monitoring_target, monitoring_metadata)
    healthy = _variant(
        base,
        hours=0,
        quality=DataQualityState.VALID,
        drift=DriftState.HEALTHY,
        performance=PerformanceState.HEALTHY,
    )
    incident = _variant(
        base,
        hours=1,
        quality=quality,
        drift=drift,
        performance=performance,
    )
    sink = RecordingAlertSink()
    store = LocalReportStore(tmp_path)
    store.publish(healthy, alert_sink=sink)
    store.publish(incident, alert_sink=sink)

    assert [item.dimension.value for item in sink.notifications] == [expected_dimension]


def test_run_state_never_success_stale_failure_and_restart_persistence(tmp_path: Path) -> None:
    config = MonitoringConfig()
    store = LocalRunStateStore(tmp_path)
    completed = datetime(2026, 1, 1, 1, 10, tzinfo=UTC)
    assert store.state_as_of(as_of=completed, config=config) is RunState.NEVER_RUN
    assert store.record_success(completed_at=completed, report_id="a" * 64)
    assert store.state_as_of(as_of=completed, config=config) is RunState.SUCCEEDED
    assert (
        LocalRunStateStore(tmp_path).state_as_of(
            as_of=completed + timedelta(hours=2), config=config
        )
        is RunState.STALE
    )
    assert store.record_failure(
        attempted_at=completed + timedelta(hours=3), reason="bounded_test_failure"
    )
    assert (
        LocalRunStateStore(tmp_path).state_as_of(
            as_of=completed + timedelta(hours=4), config=config
        )
        is RunState.FAILED
    )
    assert not store.record_success(completed_at=completed, report_id="b" * 64)


def test_local_run_state_process_lock_prevents_an_older_attempt_from_winning(
    tmp_path: Path,
) -> None:
    context = get_context("spawn")
    older_at = datetime(2026, 1, 1, 1, tzinfo=UTC)
    newer_at = older_at + timedelta(minutes=1)
    ready = tmp_path / "older-ready"
    release = tmp_path / "release-older"
    newer_started = tmp_path / "newer-started"
    newer_finished = tmp_path / "newer-finished"
    older = context.Process(
        target=_delayed_run_status_success,
        args=(str(tmp_path), older_at.isoformat(), "a" * 64, str(ready), str(release)),
    )
    newer = context.Process(
        target=_record_run_status_success,
        args=(
            str(tmp_path),
            newer_at.isoformat(),
            "b" * 64,
            str(newer_started),
            str(newer_finished),
        ),
    )
    older.start()
    try:
        assert _wait_for_marker(ready)
        newer.start()
        assert _wait_for_marker(newer_started)
        # Without a lock, the newer process completes while the older process is paused and the
        # older replace then wins. With the lock, the newer process waits and commits last.
        _wait_for_marker(newer_finished, timeout=0.5)
        release.touch()
        older.join(timeout=10)
        newer.join(timeout=10)
        assert older.exitcode == 0
        assert newer.exitcode == 0
    finally:
        release.touch(exist_ok=True)
        for process in (older, newer):
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    persisted = json.loads((tmp_path / "run-status.json").read_text(encoding="utf-8"))
    assert persisted["latest_attempt_at"] == "2026-01-01T01:01:00Z"
    assert persisted["latest_report_id"] == "b" * 64
    assert newer_finished.exists()


def test_local_run_state_same_time_updates_are_idempotent_or_conflicting(tmp_path: Path) -> None:
    store = LocalRunStateStore(tmp_path)
    completed = datetime(2026, 1, 1, 1, tzinfo=UTC)
    assert store.record_success(completed_at=completed, report_id="a" * 64)
    assert not store.record_success(completed_at=completed, report_id="a" * 64)
    with pytest.raises(ValueError, match="same-time local run-status attempts conflict"):
        store.record_success(completed_at=completed, report_id="b" * 64)


def test_emf_has_only_bounded_dimensions_counts_and_non_delivery_freshness(
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    report = _base_report(monitoring_event_factory, monitoring_target, monitoring_metadata)
    emf = build_monitor_completion_emf(
        report,
        as_of=WINDOW_END + timedelta(minutes=10),
        environment=AppEnvironment.AWS,
    )
    serialized = json.dumps(emf, sort_keys=True)
    metric = emf["_aws"]["CloudWatchMetrics"][0]
    assert metric["Dimensions"] == [["Service", "Environment"]]
    assert emf["Service"] == "monitor"
    assert emf["AcceptedTargetRecords"] == 1.0
    assert emf["ReportFreshnessSeconds"] == 600.0
    assert emf["FreshnessSemantics"] == "accepted_event_time_not_row_delivery_lateness"
    assert emf["ReportFreshnessSemantics"] == "monitor_as_of_minus_finalized_window_end"
    assert report.report_id not in serialized
    assert monitoring_target.bundle_manifest_sha256 not in serialized
    assert "event_id" not in serialized.casefold()
