"""One deterministic local monitoring run over an exactly snapshotted target and inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime, Field, field_validator

from modelguard.core.config import AppEnvironment
from modelguard.core.hashing import HashRecord
from modelguard.core.serialization import StrictArtifactModel
from modelguard.monitoring.config import MonitoringConfig, monitoring_config_hash
from modelguard.monitoring.drift import evaluate_drift
from modelguard.monitoring.events import (
    EventIdentity,
    FrozenRawSnapshot,
    MonitoringWindow,
    classify_snapshot,
    derive_baseline_identity,
    freeze_local_raw_snapshot,
    resolve_window,
    target_identity_from_bundle,
    verify_target_identity,
)
from modelguard.monitoring.performance import evaluate_delayed_performance
from modelguard.monitoring.persistence import (
    AlertSink,
    LocalReportStore,
    LocalRunStateStore,
    PublishedReport,
)
from modelguard.monitoring.report import MonitoringReport, build_monitoring_report
from modelguard.monitoring.state import assess_data_quality, ensure_utc
from modelguard.monitoring.telemetry import EmfWriter, emit_monitor_completion_emf
from modelguard.training.bundle import ValidatedBundleMetadata, inspect_bundle


class LocalMonitoringRunSpec(StrictArtifactModel):
    """Explicit local/test run inputs with no hidden active-model lookup."""

    bundle_path: Path
    event_directory: Path
    report_directory: Path
    target_identity: EventIdentity
    known_non_target_bundle_paths: list[Path] = Field(default_factory=list)
    label_directory: Path | None = None
    window_end: AwareDatetime | None = None
    as_of: AwareDatetime
    environment: AppEnvironment = AppEnvironment.LOCAL

    @field_validator("window_end", "as_of")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value, name="run timestamp") if value is not None else None


@dataclass(frozen=True)
class MonitoringRunResult:
    report: MonitoringReport
    published: PublishedReport
    monitoring_config_hash: HashRecord


@dataclass(frozen=True)
class MonitoringEvaluation:
    """Pure report evaluation shared by local files and snapshotted AWS objects."""

    report: MonitoringReport
    monitoring_config_hash: HashRecord


def evaluate_monitoring_snapshots(
    *,
    metadata: ValidatedBundleMetadata,
    target_identity: EventIdentity,
    known_non_target_metadata: tuple[ValidatedBundleMetadata, ...],
    event_snapshot: FrozenRawSnapshot,
    label_snapshot: FrozenRawSnapshot | None,
    window: MonitoringWindow,
    config: MonitoringConfig,
) -> MonitoringEvaluation:
    """Evaluate already-frozen inputs without reading storage or mutating a model."""

    policy_hash = monitoring_config_hash(config)
    verify_target_identity(metadata, target_identity)
    known_non_targets: list[EventIdentity] = []
    for known_metadata in known_non_target_metadata:
        identity = target_identity_from_bundle(known_metadata)
        if identity == target_identity or identity in known_non_targets:
            raise ValueError("known non-target bundle identities must be unique and non-target")
        known_non_targets.append(identity)
    known_non_targets.sort(
        key=lambda identity: (
            identity.model_version,
            identity.bundle_manifest_sha256,
            identity.event_schema_version,
            identity.input_schema_version,
        )
    )
    baseline_identity = derive_baseline_identity(metadata)
    classified = classify_snapshot(
        event_snapshot,
        window=window,
        target=target_identity,
        known_non_targets=known_non_targets,
    )
    drift_evaluation = evaluate_drift(classified.accepted_events, metadata.baseline, config)
    maximum_missingness = max(
        (signal.absolute_delta for signal in drift_evaluation.missingness), default=0.0
    )
    counts = classified.summary.counts
    faults = classified.summary.faults
    quality = assess_data_quality(
        raw_count=counts.raw,
        rejected_count=counts.rejected,
        accepted_target_count=counts.accepted_target,
        duplicate_count=counts.duplicate,
        known_non_target_count=counts.known_non_target,
        minimum_accepted_events=config.minimum_accepted_events,
        maximum_missingness_delta=maximum_missingness,
        reconciliation_valid=(
            counts.raw
            == counts.rejected
            + counts.outside_window
            + counts.known_non_target
            + counts.duplicate
            + counts.accepted_target
        ),
        bundle_valid=True,
        identity_fault=(
            faults.unknown_identity_records > 0 or faults.conflicting_identity_records > 0
        ),
        conflicting_event_id_fault=faults.conflicting_event_id_groups > 0,
        config=config,
    )
    reference_cost = metadata.metrics.held_out_test.synthetic_cost_per_event.value
    if reference_cost is None:
        raise ValueError("verified bundle lacks an evaluable held-out synthetic reference cost")
    performance = evaluate_delayed_performance(
        classified.accepted_events,
        label_snapshot=label_snapshot,
        locked_threshold=metadata.threshold.threshold,
        held_out_reference_cost_per_event=float(reference_cost),
        config=config,
    )
    report = build_monitoring_report(
        window=window,
        target=target_identity,
        baseline=baseline_identity,
        config=config,
        config_hash=policy_hash,
        known_non_targets=known_non_targets,
        classified=classified,
        quality=quality,
        drift_evaluation=drift_evaluation,
        performance=performance,
    )
    return MonitoringEvaluation(report=report, monitoring_config_hash=policy_hash)


def run_local_monitoring(
    spec: LocalMonitoringRunSpec,
    *,
    config: MonitoringConfig | None = None,
    report_store: LocalReportStore | None = None,
    run_state_store: LocalRunStateStore | None = None,
    alert_sink: AlertSink | None = None,
    emf_writer: EmfWriter | None = None,
) -> MonitoringRunResult:
    """Freeze inputs, verify exact bundles, evaluate dimensions, and publish atomically."""

    policy = config or MonitoringConfig()
    window = resolve_window(as_of=spec.as_of, config=policy, window_end=spec.window_end)

    # Raw records and optional labels are copied before any analysis so later appends cannot change
    # this run. Paths, object names, and file boundaries never enter the report identity.
    event_snapshot = freeze_local_raw_snapshot(spec.event_directory)
    label_snapshot = (
        freeze_local_raw_snapshot(spec.label_directory)
        if spec.label_directory is not None
        else None
    )

    metadata = inspect_bundle(spec.bundle_path)
    known_metadata = tuple(
        inspect_bundle(bundle_path) for bundle_path in spec.known_non_target_bundle_paths
    )
    evaluation = evaluate_monitoring_snapshots(
        metadata=metadata,
        target_identity=spec.target_identity,
        known_non_target_metadata=known_metadata,
        event_snapshot=event_snapshot,
        label_snapshot=label_snapshot,
        window=window,
        config=policy,
    )
    report = evaluation.report

    publisher = report_store or LocalReportStore(spec.report_directory)
    published = publisher.publish(report, alert_sink=alert_sink)
    if spec.environment is AppEnvironment.AWS:
        if emf_writer is None:
            emit_monitor_completion_emf(
                report,
                as_of=spec.as_of,
                environment=spec.environment,
            )
        else:
            emit_monitor_completion_emf(
                report,
                as_of=spec.as_of,
                environment=spec.environment,
                writer=emf_writer,
            )
    status_store = run_state_store or LocalRunStateStore(spec.report_directory)
    status_store.record_success(completed_at=spec.as_of, report_id=report.report_id)
    return MonitoringRunResult(
        report=report,
        published=published,
        monitoring_config_hash=evaluation.monitoring_config_hash,
    )
