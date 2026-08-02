"""Independent run, data-quality, drift, and performance state policies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from modelguard.core.serialization import StrictArtifactModel
from modelguard.monitoring.config import MonitoringConfig


class RunState(StrEnum):
    NEVER_RUN = "never_run"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"


class DataQualityState(StrEnum):
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"
    INSUFFICIENT_DATA = "insufficient_data"


class DriftState(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class PerformanceState(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    PENDING_LABELS = "pending_labels"
    UNKNOWN = "unknown"


class DataQualityAssessment(StrictArtifactModel):
    state: DataQualityState
    reasons: list[str]
    rejected_fraction: float | None = Field(default=None, ge=0.0, le=1.0)


def determine_run_state(
    *,
    current_attempt_failed: bool,
    latest_success_at: datetime | None,
    as_of: datetime,
    stale_after: timedelta,
) -> RunState:
    """Apply failure, never-run, stale-success, succeeded precedence."""

    if current_attempt_failed:
        return RunState.FAILED
    if latest_success_at is None:
        return RunState.NEVER_RUN
    if as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be expressed in UTC")
    if latest_success_at.utcoffset() != timedelta(0):
        raise ValueError("latest_success_at must be expressed in UTC")
    if as_of < latest_success_at:
        raise ValueError("as_of cannot precede the latest successful run")
    if as_of - latest_success_at >= stale_after:
        return RunState.STALE
    return RunState.SUCCEEDED


def assess_data_quality(
    *,
    raw_count: int,
    rejected_count: int,
    accepted_target_count: int,
    duplicate_count: int,
    known_non_target_count: int,
    minimum_accepted_events: int,
    maximum_missingness_delta: float,
    reconciliation_valid: bool,
    bundle_valid: bool,
    identity_fault: bool,
    conflicting_event_id_fault: bool,
    config: MonitoringConfig,
) -> DataQualityAssessment:
    """Apply invalid, insufficient, warning, valid precedence exactly once."""

    if (
        min(
            raw_count,
            rejected_count,
            accepted_target_count,
            duplicate_count,
            known_non_target_count,
        )
        < 0
    ):
        raise ValueError("record counts cannot be negative")
    if not 0.0 <= maximum_missingness_delta <= 1.0:
        raise ValueError("missingness delta must be in [0, 1]")
    rejected_fraction = rejected_count / raw_count if raw_count else None
    invalid_reasons: list[str] = []
    if not reconciliation_valid:
        invalid_reasons.append("record_count_reconciliation_failed")
    if not bundle_valid:
        invalid_reasons.append("target_bundle_verification_failed")
    if identity_fault:
        invalid_reasons.append("unknown_or_conflicting_identity")
    if conflicting_event_id_fault:
        invalid_reasons.append("conflicting_event_id_group")
    if maximum_missingness_delta >= config.missingness_invalid_threshold:
        invalid_reasons.append("missingness_invalid_boundary")
    if (
        rejected_fraction is not None
        and rejected_fraction >= config.rejected_fraction_invalid_threshold
    ):
        invalid_reasons.append("rejected_fraction_invalid_boundary")
    if invalid_reasons:
        return DataQualityAssessment(
            state=DataQualityState.INVALID,
            reasons=invalid_reasons,
            rejected_fraction=rejected_fraction,
        )
    if accepted_target_count < minimum_accepted_events:
        return DataQualityAssessment(
            state=DataQualityState.INSUFFICIENT_DATA,
            reasons=["accepted_target_below_minimum"],
            rejected_fraction=rejected_fraction,
        )
    warning_reasons: list[str] = []
    if rejected_count:
        warning_reasons.append("rejected_records_present")
    if duplicate_count:
        warning_reasons.append("benign_duplicates_present")
    if known_non_target_count:
        warning_reasons.append("known_non_target_records_present")
    if maximum_missingness_delta >= config.missingness_warning_threshold:
        warning_reasons.append("missingness_warning_boundary")
    if warning_reasons:
        return DataQualityAssessment(
            state=DataQualityState.WARNING,
            reasons=warning_reasons,
            rejected_fraction=rejected_fraction,
        )
    return DataQualityAssessment(
        state=DataQualityState.VALID,
        reasons=["all_quality_checks_passed"],
        rejected_fraction=rejected_fraction,
    )


def aggregate_drift_state(
    severities: list[DriftState],
    *,
    data_quality_state: DataQualityState,
) -> DriftState:
    """Return the strongest evaluable required signal without inventing health."""

    if data_quality_state in {
        DataQualityState.INVALID,
        DataQualityState.INSUFFICIENT_DATA,
    }:
        return DriftState.UNKNOWN
    if not severities:
        return DriftState.UNKNOWN
    if DriftState.DEGRADED in severities:
        return DriftState.DEGRADED
    if DriftState.WARNING in severities:
        return DriftState.WARNING
    if DriftState.UNKNOWN in severities:
        return DriftState.UNKNOWN
    return DriftState.HEALTHY


def performance_state_from_delta(delta: float, config: MonitoringConfig) -> PerformanceState:
    """Classify exact decimal threshold boundaries without binary-float surprises."""

    value = Decimal(str(delta))
    if value >= Decimal(str(config.performance_degraded_delta)):
        return PerformanceState.DEGRADED
    if value >= Decimal(str(config.performance_warning_delta)):
        return PerformanceState.WARNING
    return PerformanceState.HEALTHY


def ensure_utc(value: datetime, *, name: str) -> datetime:
    """Return a normalized UTC datetime while rejecting naive/non-UTC inputs."""

    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be expressed in UTC")
    return value.astimezone(UTC)
