"""Strict parsing and honest freshness/view-state assembly for dashboard artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import Field

from modelguard.core.hashing import sha256_bytes
from modelguard.core.serialization import StrictArtifactModel, parse_strict_json_bytes
from modelguard.dashboard.repository import (
    DashboardRepository,
    DashboardRepositoryError,
    RawArtifact,
)
from modelguard.monitoring.config import MonitoringConfig, monitoring_config_hash
from modelguard.monitoring.persistence import RunStatusArtifact
from modelguard.monitoring.report import MonitoringReport
from modelguard.monitoring.state import RunState, determine_run_state, ensure_utc
from modelguard.training.bundle import ModelManifest


class ArtifactAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DashboardIssue:
    code: str
    severity: IssueSeverity
    message: str


class ActiveModelIdentity(StrictArtifactModel):
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_contract_version: str


@dataclass(frozen=True)
class DashboardSnapshot:
    captured_at: datetime
    report_availability: ArtifactAvailability
    run_status_availability: ArtifactAvailability
    active_model_availability: ArtifactAvailability
    latest_report: MonitoringReport | None
    run_status: RunStatusArtifact | None
    active_model: ActiveModelIdentity | None
    recent_reports: tuple[MonitoringReport, ...]
    run_state: RunState | None
    report_completed_at: datetime | None
    report_age_seconds: float | None
    window_age_seconds: float | None
    accepted_event_age_seconds: float | None
    freshness_boundary_seconds: int | None
    monitoring_policy: MonitoringConfig | None
    policy_matches_report: bool | None
    active_matches_report_target: bool | None
    issues: tuple[DashboardIssue, ...]


def parse_monitoring_report(artifact: RawArtifact) -> MonitoringReport:
    """Parse one strict report, including duplicate-key/non-finite rejection."""

    return MonitoringReport.model_validate(parse_strict_json_bytes(artifact.payload))


def parse_run_status(artifact: RawArtifact) -> RunStatusArtifact:
    """Parse the mutable run-health artifact independently from the latest report."""

    return RunStatusArtifact.model_validate(parse_strict_json_bytes(artifact.payload))


def parse_active_model_manifest(
    artifact: RawArtifact,
    *,
    expected_model_version: str,
) -> ActiveModelIdentity:
    """Derive the configured active identity from strict manifest bytes without loading joblib."""

    manifest = ModelManifest.model_validate(parse_strict_json_bytes(artifact.payload))
    if manifest.model_version != expected_model_version:
        raise ValueError("active manifest version differs from configured active version")
    return ActiveModelIdentity(
        model_version=manifest.model_version,
        manifest_sha256=sha256_bytes(artifact.payload),
        input_schema_sha256=manifest.lineage.input_schema_hash.digest,
        manifest_contract_version=manifest.contract_version,
    )


def _repository_issue(category: str, artifact_name: str) -> DashboardIssue:
    return DashboardIssue(
        code=f"{artifact_name}_repository_unavailable",
        severity=IssueSeverity.ERROR,
        message=(
            f"The {artifact_name.replace('_', ' ')} could not be read from the configured "
            f"repository ({category}). No state is inferred from it."
        ),
    )


def _safe_age(later: datetime, earlier: datetime) -> float | None:
    seconds = (later - earlier).total_seconds()
    return seconds if seconds >= 0.0 else None


def load_dashboard_snapshot(
    repository: DashboardRepository,
    *,
    expected_active_model_version: str,
    monitoring_policy: MonitoringConfig | None,
    captured_at: datetime,
    history_limit: int,
    policy_problem: str | None = None,
) -> DashboardSnapshot:
    """Load independent evidence dimensions without converting missing data into health."""

    now = ensure_utc(captured_at, name="dashboard captured_at")
    issues: list[DashboardIssue] = []

    report_artifact: RawArtifact | None = None
    report: MonitoringReport | None = None
    report_availability = ArtifactAvailability.MISSING
    try:
        report_artifact = repository.read_latest_report()
    except DashboardRepositoryError as error:
        report_availability = ArtifactAvailability.UNAVAILABLE
        issues.append(_repository_issue(error.category, "latest_report"))
    else:
        if report_artifact is None:
            issues.append(
                DashboardIssue(
                    code="latest_report_missing",
                    severity=IssueSeverity.WARNING,
                    message="No successful monitoring report is available yet.",
                )
            )
        else:
            try:
                report = parse_monitoring_report(report_artifact)
            except ValueError:
                report_availability = ArtifactAvailability.MALFORMED
                issues.append(
                    DashboardIssue(
                        code="latest_report_malformed",
                        severity=IssueSeverity.ERROR,
                        message=(
                            "The latest monitoring report failed its strict contract. "
                            "Report-backed states are unavailable."
                        ),
                    )
                )
            else:
                report_availability = ArtifactAvailability.AVAILABLE

    status: RunStatusArtifact | None = None
    status_availability = ArtifactAvailability.MISSING
    try:
        status_artifact = repository.read_run_status()
    except DashboardRepositoryError as error:
        status_availability = ArtifactAvailability.UNAVAILABLE
        issues.append(_repository_issue(error.category, "run_status"))
    else:
        if status_artifact is None:
            if report is not None:
                issues.append(
                    DashboardIssue(
                        code="run_status_missing",
                        severity=IssueSeverity.ERROR,
                        message=(
                            "A report exists but run-status evidence is missing; current run "
                            "freshness cannot be established."
                        ),
                    )
                )
        else:
            try:
                status = parse_run_status(status_artifact)
            except ValueError:
                status_availability = ArtifactAvailability.MALFORMED
                issues.append(
                    DashboardIssue(
                        code="run_status_malformed",
                        severity=IssueSeverity.ERROR,
                        message=(
                            "The monitor run-status artifact failed its strict contract; current "
                            "run state is unknown."
                        ),
                    )
                )
            else:
                status_availability = ArtifactAvailability.AVAILABLE

    active_model: ActiveModelIdentity | None = None
    active_availability = ArtifactAvailability.MISSING
    try:
        active_artifact = repository.read_active_model_manifest()
    except DashboardRepositoryError as error:
        active_availability = ArtifactAvailability.UNAVAILABLE
        issues.append(_repository_issue(error.category, "active_model_manifest"))
    else:
        if active_artifact is None:
            issues.append(
                DashboardIssue(
                    code="active_model_manifest_missing",
                    severity=IssueSeverity.WARNING,
                    message="The configured active model manifest is unavailable.",
                )
            )
        else:
            try:
                active_model = parse_active_model_manifest(
                    active_artifact,
                    expected_model_version=expected_active_model_version,
                )
            except ValueError:
                active_availability = ArtifactAvailability.MALFORMED
                issues.append(
                    DashboardIssue(
                        code="active_model_manifest_malformed",
                        severity=IssueSeverity.ERROR,
                        message=(
                            "The configured active model manifest failed identity validation."
                        ),
                    )
                )
            else:
                active_availability = ArtifactAvailability.AVAILABLE

    if monitoring_policy is None:
        issues.append(
            DashboardIssue(
                code="monitoring_policy_unavailable",
                severity=IssueSeverity.ERROR,
                message=(
                    "The versioned monitoring policy is unavailable"
                    f"{f' ({policy_problem})' if policy_problem else ''}; freshness and metric "
                    "thresholds are not inferred."
                ),
            )
        )

    policy_matches: bool | None = None
    if report is not None and monitoring_policy is not None:
        policy_matches = (
            monitoring_config_hash(monitoring_policy) == report.identities.monitoring_config_hash
        )
        if not policy_matches:
            issues.append(
                DashboardIssue(
                    code="monitoring_policy_identity_mismatch",
                    severity=IssueSeverity.ERROR,
                    message=(
                        "The available monitoring policy does not match the report's recorded "
                        "configuration identity; thresholds and freshness state are withheld."
                    ),
                )
            )

    status_consistent = status is not None
    if status is not None:
        if status.latest_attempt_at > now:
            status_consistent = False
            issues.append(
                DashboardIssue(
                    code="run_status_future_timestamp",
                    severity=IssueSeverity.ERROR,
                    message="Run-status timestamps are later than the dashboard snapshot time.",
                )
            )
        if (
            status.latest_success_at is not None
            and status.latest_success_at > status.latest_attempt_at
        ):
            status_consistent = False
            issues.append(
                DashboardIssue(
                    code="run_status_chronology_invalid",
                    severity=IssueSeverity.ERROR,
                    message="Run-status success/attempt timestamps do not reconcile.",
                )
            )
        if report is None and status.latest_report_id is not None:
            status_consistent = False
            issues.append(
                DashboardIssue(
                    code="status_report_missing",
                    severity=IssueSeverity.ERROR,
                    message="Run status references a successful report that is unavailable.",
                )
            )
        if report is not None:
            if status.latest_report_id != report.report_id:
                status_consistent = False
                issues.append(
                    DashboardIssue(
                        code="status_report_identity_mismatch",
                        severity=IssueSeverity.ERROR,
                        message="Run status and latest report IDs do not match.",
                    )
                )
            if (
                status.latest_success_at is None
                or status.latest_success_at < report.window.eligible_at
            ):
                status_consistent = False
                issues.append(
                    DashboardIssue(
                        code="status_report_timestamp_mismatch",
                        severity=IssueSeverity.ERROR,
                        message="Run completion time is inconsistent with report finalization.",
                    )
                )

    run_state: RunState | None = None
    freshness_boundary: int | None = None
    current_failure_evidenced = (
        status is not None
        and status.latest_attempt_state == "failed"
        and status.latest_attempt_at <= now
        and (
            status.latest_success_at is None or status.latest_success_at <= status.latest_attempt_at
        )
    )
    if current_failure_evidenced:
        run_state = RunState.FAILED
    elif status is not None and status_consistent:
        if report is not None and monitoring_policy is not None and policy_matches:
            freshness_boundary = monitoring_policy.stale_after_seconds
            run_state = determine_run_state(
                current_attempt_failed=False,
                latest_success_at=status.latest_success_at,
                as_of=now,
                stale_after=timedelta(seconds=freshness_boundary),
            )
    elif (
        status_availability is ArtifactAvailability.MISSING
        and report_availability is ArtifactAvailability.MISSING
    ):
        run_state = RunState.NEVER_RUN

    report_completed_at = (
        status.latest_success_at
        if status is not None and status_consistent and report is not None
        else None
    )
    report_age = _safe_age(now, report_completed_at) if report_completed_at is not None else None
    window_age = _safe_age(now, report.window.end) if report is not None else None
    event_age = (
        _safe_age(now, report.records.max_accepted_event_timestamp)
        if report is not None and report.records.max_accepted_event_timestamp is not None
        else None
    )
    if report is not None and (
        window_age is None or (event_age is None and report.records.counts.accepted_target)
    ):
        issues.append(
            DashboardIssue(
                code="report_data_timestamp_future",
                severity=IssueSeverity.ERROR,
                message="Report data timestamps are later than the dashboard snapshot time.",
            )
        )

    active_matches: bool | None = None
    if report is not None and active_model is not None:
        target = report.identities.event_carried_target
        active_matches = (
            active_model.model_version == target.model_version
            and active_model.manifest_sha256 == target.bundle_manifest_sha256
        )
        if not active_matches:
            issues.append(
                DashboardIssue(
                    code="active_report_target_differ",
                    severity=IssueSeverity.INFO,
                    message=(
                        "The active model differs from this report's target. The report remains "
                        "historical evidence for its recorded target only."
                    ),
                )
            )

    history: list[MonitoringReport] = []
    malformed_history = 0
    try:
        history_artifacts = repository.list_recent_reports(limit=history_limit)
    except DashboardRepositoryError as error:
        issues.append(_repository_issue(error.category, "report_history"))
    else:
        seen: set[str] = set()
        for artifact in history_artifacts:
            try:
                historical = parse_monitoring_report(artifact)
            except ValueError:
                malformed_history += 1
                continue
            if historical.report_id not in seen:
                seen.add(historical.report_id)
                history.append(historical)
        if malformed_history:
            issues.append(
                DashboardIssue(
                    code="report_history_malformed",
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"{malformed_history} malformed historical report artifact(s) were "
                        "omitted from trends."
                    ),
                )
            )
    if report is not None and all(item.report_id != report.report_id for item in history):
        history.append(report)
    history.sort(key=lambda item: (item.window.end, item.report_id))
    history = history[-history_limit:]

    return DashboardSnapshot(
        captured_at=now.astimezone(UTC),
        report_availability=report_availability,
        run_status_availability=status_availability,
        active_model_availability=active_availability,
        latest_report=report,
        run_status=status,
        active_model=active_model,
        recent_reports=tuple(history),
        run_state=run_state,
        report_completed_at=report_completed_at,
        report_age_seconds=report_age,
        window_age_seconds=window_age,
        accepted_event_age_seconds=event_age,
        freshness_boundary_seconds=freshness_boundary,
        monitoring_policy=monitoring_policy if policy_matches is not False else None,
        policy_matches_report=policy_matches,
        active_matches_report_target=active_matches,
        issues=tuple(issues),
    )
