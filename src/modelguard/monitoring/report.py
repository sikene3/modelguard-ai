"""Strict deterministic monitoring report contract, identity, and offline HTML rendering."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from html import escape
from typing import Any, Literal

from pydantic import Field, model_validator

from modelguard.core.hashing import HashRecord, canonical_json_hash
from modelguard.core.serialization import StrictArtifactModel
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.drift import DriftEvaluation
from modelguard.monitoring.events import (
    BaselineIdentity,
    ClassifiedEvents,
    EventClassificationSummary,
    EventIdentity,
    MonitoringWindow,
)
from modelguard.monitoring.performance import EvaluatedPerformance, PerformanceEvaluation
from modelguard.monitoring.state import (
    DataQualityAssessment,
    DataQualityState,
    DriftState,
    PerformanceState,
    RunState,
    aggregate_drift_state,
    ensure_utc,
)

MONITORING_REPORT_SCHEMA_VERSION: Literal["modelguard.monitoring-report.v1"] = (
    "modelguard.monitoring-report.v1"
)


class MonitoringStates(StrictArtifactModel):
    run: RunState
    data_quality: DataQualityState
    drift: DriftState
    performance: PerformanceState


class MonitoringIdentities(StrictArtifactModel):
    event_carried_target: EventIdentity
    baseline_derived_from_verified_manifest: BaselineIdentity
    monitoring_config_version: Literal["modelguard.monitoring-config.v1"]
    monitoring_config_hash: HashRecord
    known_non_target_identities: list[EventIdentity]


class DataQualityReport(StrictArtifactModel):
    assessment: DataQualityAssessment
    maximum_missingness_delta: float = Field(ge=0.0, le=1.0)


class DriftReport(StrictArtifactModel):
    state: DriftState
    reason: str
    evaluation: DriftEvaluation


class ReportIdentityContract(StrictArtifactModel):
    hash: HashRecord
    selected_record_digest_count: int = Field(ge=0)
    label_digest_count: int = Field(ge=0)


class MonitoringReport(StrictArtifactModel):
    """One immutable successful monitoring result with four independent states."""

    report_schema_version: Literal["modelguard.monitoring-report.v1"] = (
        MONITORING_REPORT_SCHEMA_VERSION
    )
    report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_identity: ReportIdentityContract
    window: MonitoringWindow
    identities: MonitoringIdentities
    states: MonitoringStates
    records: EventClassificationSummary
    data_quality: DataQualityReport
    drift: DriftReport
    performance: PerformanceEvaluation
    limitations: list[str]

    @model_validator(mode="after")
    def validate_independent_states(self) -> MonitoringReport:
        if self.report_id != self.report_identity.hash.digest:
            raise ValueError("report_id must equal its canonical report-identity digest")
        if self.states.run is not RunState.SUCCEEDED:
            raise ValueError("immutable monitoring reports represent successful monitor runs only")
        if self.states.data_quality is not self.data_quality.assessment.state:
            raise ValueError("data-quality state differs from its section")
        if self.states.drift is not self.drift.state:
            raise ValueError("drift state differs from its section")
        if self.states.performance is not self.performance.state:
            raise ValueError("performance state differs from its section")
        return self


def canonical_report_identity(
    *,
    window: MonitoringWindow,
    target: EventIdentity,
    baseline: BaselineIdentity,
    config_hash: HashRecord,
    classified_record_digests: tuple[str, ...],
    classified_label_digests: tuple[str, ...],
    known_non_targets: Sequence[EventIdentity] = (),
    label_source_configured: bool = False,
    label_evaluation_cutoff: datetime | None = None,
) -> ReportIdentityContract:
    """Hash only canonical semantic inputs, never storage layout or mutable file identity."""

    if label_source_configured != (label_evaluation_cutoff is not None):
        raise ValueError("configured label sources require an identity-bound evaluation cutoff")
    serialized_cutoff = None
    if label_evaluation_cutoff is not None:
        serialized_cutoff = (
            ensure_utc(label_evaluation_cutoff, name="label_evaluation_cutoff")
            .isoformat()
            .replace("+00:00", "Z")
        )

    serialized_window = window.model_dump(mode="json")
    payload = {
        "report_schema_version": MONITORING_REPORT_SCHEMA_VERSION,
        "window": {
            "start": serialized_window["start"],
            "end": serialized_window["end"],
            "duration_seconds": window.duration_seconds,
            "finalization_grace_seconds": window.finalization_grace_seconds,
        },
        "target_identity": target,
        "baseline_identity": baseline,
        "monitoring_config_identity": config_hash,
        "known_non_target_identities": sorted(
            known_non_targets,
            key=lambda identity: (
                identity.event_schema_version,
                identity.model_version,
                identity.bundle_manifest_sha256,
                identity.input_schema_version,
            ),
        ),
        "label_source_configured": label_source_configured,
        "label_evaluation_cutoff": serialized_cutoff,
        "selected_record_classification_digests": sorted(classified_record_digests),
        "label_classification_digests": sorted(classified_label_digests),
    }
    identity_hash = canonical_json_hash(
        payload,
        canonicalization_version="modelguard.monitoring-report-identity.v2",
        ordering=(
            "canonical JSON keys ascending; known identities canonical-tuple ascending; record "
            "and label classification-digest multisets ascending"
        ),
        exclusions=[
            "input enumeration order",
            "storage object name",
            "file boundary",
            "mutable enclosing-file hash",
            "monitor invocation time when no label source is configured",
            "HTML presentation",
        ],
    )
    return ReportIdentityContract(
        hash=identity_hash,
        selected_record_digest_count=len(classified_record_digests),
        label_digest_count=len(classified_label_digests),
    )


def build_monitoring_report(
    *,
    window: MonitoringWindow,
    target: EventIdentity,
    baseline: BaselineIdentity,
    config: MonitoringConfig,
    config_hash: HashRecord,
    known_non_targets: list[EventIdentity],
    classified: ClassifiedEvents,
    quality: DataQualityAssessment,
    drift_evaluation: DriftEvaluation,
    performance: EvaluatedPerformance,
) -> MonitoringReport:
    """Assemble one deterministic report after all independent evaluations complete."""

    drift_state = aggregate_drift_state(
        [signal.state for signal in drift_evaluation.signals],
        data_quality_state=quality.state,
    )
    if quality.state.value in {"invalid", "insufficient_data"}:
        drift_reason = "data_quality_blocks_drift_state"
    elif drift_state is DriftState.UNKNOWN:
        drift_reason = "one_or_more_required_signals_unevaluable"
    else:
        drift_reason = "maximum_required_signal_severity"
    maximum_missingness = max(
        (signal.absolute_delta for signal in drift_evaluation.missingness), default=0.0
    )
    identity = canonical_report_identity(
        window=window,
        target=target,
        baseline=baseline,
        config_hash=config_hash,
        classified_record_digests=classified.classified_record_digests,
        classified_label_digests=performance.classified_label_digests,
        known_non_targets=known_non_targets,
        label_source_configured=performance.evaluation.label_source_configured,
        label_evaluation_cutoff=performance.evaluation.evaluation_cutoff,
    )
    return MonitoringReport(
        report_id=identity.hash.digest,
        report_identity=identity,
        window=window,
        identities=MonitoringIdentities(
            event_carried_target=target,
            baseline_derived_from_verified_manifest=baseline,
            monitoring_config_version=config.contract_version,
            monitoring_config_hash=config_hash,
            known_non_target_identities=known_non_targets,
        ),
        states=MonitoringStates(
            run=RunState.SUCCEEDED,
            data_quality=quality.state,
            drift=drift_state,
            performance=performance.evaluation.state,
        ),
        records=classified.summary,
        data_quality=DataQualityReport(
            assessment=quality,
            maximum_missingness_delta=maximum_missingness,
        ),
        drift=DriftReport(
            state=drift_state,
            reason=drift_reason,
            evaluation=drift_evaluation,
        ),
        performance=performance.evaluation,
        limitations=[
            "Drift is distribution change, not an accuracy or causal performance claim.",
            "Performance applies only to the labeled subset and is not inferred from drift.",
            "Partial-label selection bias may make the labeled subset unrepresentative.",
            "Finalization grace is a closing delay; row-level delivery lateness is not measured.",
            "Synthetic policy costs are demo heuristics, not real-world business economics.",
            "KS is intentionally omitted from this MVP.",
        ],
    )


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _metric(value: float | None) -> str:
    return "not evaluable" if value is None else f"{value:.6f}"


def render_offline_html(report: MonitoringReport) -> str:
    """Render escaped, deterministic, dependency-free HTML with no external resources."""

    counts = report.records.counts
    state_rows = "".join(
        f"<tr><th>{_text(name)}</th><td>{_text(value)}</td></tr>"
        for name, value in (
            ("Run", report.states.run.value),
            ("Data quality", report.states.data_quality.value),
            ("Drift", report.states.drift.value),
            ("Performance", report.states.performance.value),
        )
    )
    count_rows = "".join(
        f"<tr><th>{_text(name)}</th><td>{value}</td></tr>"
        for name, value in (
            ("Raw", counts.raw),
            ("Rejected", counts.rejected),
            ("Outside window", counts.outside_window),
            ("Known non-target", counts.known_non_target),
            ("Duplicate", counts.duplicate),
            ("Accepted target", counts.accepted_target),
        )
    )
    signal_rows = "".join(
        "<tr>"
        f"<td>{_text(signal.name)}</td>"
        f"<td>{_text(signal.kind)}</td>"
        f"<td>{_text(_metric(signal.value))}</td>"
        f"<td>{_text(signal.state.value)}</td>"
        f"<td>{_text(signal.reason)}</td>"
        "</tr>"
        for signal in report.drift.evaluation.signals
    )
    missingness_rows = "".join(
        "<tr>"
        f"<td>{_text(signal.feature)}</td>"
        f"<td>{signal.baseline_rate:.6f}</td>"
        f"<td>{signal.current_rate:.6f}</td>"
        f"<td>{signal.absolute_delta:.6f}</td>"
        f"<td>{_text(signal.state)}</td>"
        "</tr>"
        for signal in report.drift.evaluation.missingness
    )
    performance_metrics = report.performance.metrics
    if performance_metrics is None:
        performance_html = (
            f"<p>Metrics not computed: {_text(report.performance.reason)}. "
            f"Coverage: {_text(report.performance.coverage)}.</p>"
        )
    else:
        performance_html = (
            "<table><tbody>"
            f"<tr><th>Rows</th><td>{performance_metrics.row_count}</td></tr>"
            "<tr><th>Average precision</th><td>"
            f"{performance_metrics.average_precision:.6f}</td></tr>"
            f"<tr><th>ROC-AUC</th><td>{performance_metrics.roc_auc:.6f}</td></tr>"
            f"<tr><th>Brier</th><td>{performance_metrics.brier_score:.6f}</td></tr>"
            f"<tr><th>Log loss</th><td>{performance_metrics.log_loss:.6f}</td></tr>"
            "<tr><th>Synthetic cost delta</th><td>"
            f"{performance_metrics.synthetic_cost_delta:.6f}</td></tr>"
            "</tbody></table>"
        )
    limitations = "".join(f"<li>{_text(item)}</li>" for item in report.limitations)
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>ModelGuard monitoring report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;"
        "padding:0 1rem;color:#18212b}table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "th,td{border:1px solid #ccd3da;padding:.45rem;text-align:left}th{background:#f3f5f7}"
        "code{overflow-wrap:anywhere}h1,h2{color:#12395b}</style></head><body>"
        "<h1>ModelGuard monitoring report</h1>"
        f"<p><strong>Report ID:</strong> <code>{_text(report.report_id)}</code></p>"
        f"<p><strong>Window:</strong> {_text(report.window.start.isoformat())} to "
        f"{_text(report.window.end.isoformat())} (half-open, UTC); eligible after "
        f"{_text(report.window.eligible_at.isoformat())}.</p>"
        "<h2>Independent states</h2><table><tbody>"
        f"{state_rows}</tbody></table>"
        "<h2>Exclusive record reconciliation</h2><table><tbody>"
        f"{count_rows}</tbody></table>"
        "<h2>Required drift signals</h2><table><thead><tr><th>Signal</th><th>Metric</th>"
        f"<th>Value</th><th>State</th><th>Reason</th></tr></thead><tbody>{signal_rows}"
        "</tbody></table>"
        "<h2>Separate missingness assessment</h2><table><thead><tr><th>Feature</th>"
        "<th>Baseline</th><th>Current</th><th>Absolute delta</th><th>Quality</th></tr>"
        f"</thead><tbody>{missingness_rows}</tbody></table>"
        f"<h2>Delayed performance</h2><p>{_text(report.performance.interpretation)}.</p>"
        f"{performance_html}<h2>Limitations</h2><ul>{limitations}</ul>"
        "</body></html>\n"
    )


def monitoring_report_json_schema() -> dict[str, Any]:
    """Return the portable checked-in JSON Schema for the strict report model."""

    schema = MonitoringReport.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://modelguard.example/contracts/monitoring-report-v1.schema.json"
    return schema
