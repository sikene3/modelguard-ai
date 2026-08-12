"""Immutable local report history, monotonic latest, alerts, and persistent run health."""

from __future__ import annotations

import fcntl
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field, model_validator

from modelguard.core.hashing import sha256_bytes
from modelguard.core.serialization import (
    StrictArtifactModel,
    canonical_json_bytes,
    validate_strict_json_model,
)
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.report import MonitoringReport, render_offline_html
from modelguard.monitoring.state import RunState, determine_run_state, ensure_utc


class AlertDimension(StrEnum):
    DATA_QUALITY = "data_quality"
    DRIFT = "drift"
    PERFORMANCE = "performance"


class AlertSendStatus(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class AlertNotification(StrictArtifactModel):
    report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    window_end: AwareDatetime
    dimension: AlertDimension
    previous_state: str | None
    current_state: str
    message: str


class AlertSendResult(StrictArtifactModel):
    status: AlertSendStatus
    provider_message_id: str | None = None
    failure_category: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AlertSendResult:
        if self.status is AlertSendStatus.SENT and self.failure_category is not None:
            raise ValueError("sent alerts cannot have a failure category")
        if self.status is AlertSendStatus.FAILED and self.failure_category is None:
            raise ValueError("failed alerts require a bounded failure category")
        if self.status is AlertSendStatus.NOT_CONFIGURED and (
            self.provider_message_id is not None or self.failure_category is not None
        ):
            raise ValueError("unconfigured alerts cannot have provider details")
        return self


class AlertSink(Protocol):
    def send(self, notification: AlertNotification) -> AlertSendResult:
        """Return a bounded outcome; implementations must not leak provider exception text."""


class UnconfiguredAlertSink:
    def send(self, notification: AlertNotification) -> AlertSendResult:
        del notification
        return AlertSendResult(status=AlertSendStatus.NOT_CONFIGURED)


class AlertMarker(StrictArtifactModel):
    marker_schema_version: Literal["modelguard.alert-marker.v1"] = "modelguard.alert-marker.v1"
    notification: AlertNotification
    claim_status: Literal["claimed"] = "claimed"
    send_result: AlertSendResult | None
    delivery_semantics: Literal[
        "conditional_claim_suppresses_routine_retries_but_does_not_guarantee_exactly_once_delivery"
    ] = "conditional_claim_suppresses_routine_retries_but_does_not_guarantee_exactly_once_delivery"


@dataclass(frozen=True)
class PublishedReport:
    json_path: Path
    html_path: Path
    json_sha256: str
    html_sha256: str
    latest_updated: bool
    alert_markers: tuple[Path, ...]


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("atomic file write made no progress")
        offset += written


def _create_if_absent(path: Path, payload: bytes) -> bool:
    """Publish complete bytes at ``path`` without ever exposing a partial destination."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            # A same-directory hard link makes the fully written inode visible atomically while
            # retaining create-if-absent semantics across processes.
            os.link(temporary, path, follow_symlinks=False)
            directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except FileExistsError:
            if path.is_symlink() or not path.is_file():
                raise OSError("immutable artifact path is not a regular file") from None
            if path.read_bytes() != payload:
                raise FileExistsError(
                    "immutable artifact identity already has different bytes"
                ) from None
            return False
        return True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_report(path: Path) -> MonitoringReport | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise OSError("latest report path must be a regular file")
    return validate_strict_json_model(path.read_bytes(), MonitoringReport)


def _dimension_states(report: MonitoringReport) -> dict[AlertDimension, tuple[str, str]]:
    return {
        AlertDimension.DATA_QUALITY: (report.states.data_quality.value, "invalid"),
        AlertDimension.DRIFT: (report.states.drift.value, "degraded"),
        AlertDimension.PERFORMANCE: (report.states.performance.value, "degraded"),
    }


class LocalReportStore:
    """Create immutable history and conditionally advance one process-safe latest report."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise OSError("report root must be a non-symlink directory")

    def _claim_transition_markers(
        self,
        report: MonitoringReport,
        previous: MonitoringReport | None,
    ) -> list[tuple[Path, AlertNotification]]:
        previous_states = _dimension_states(previous) if previous is not None else {}
        claims: list[tuple[Path, AlertNotification]] = []
        for dimension, (current_state, alert_state) in _dimension_states(report).items():
            previous_state = previous_states[dimension][0] if dimension in previous_states else None
            if current_state != alert_state or previous_state == alert_state:
                continue
            notification = AlertNotification(
                report_id=report.report_id,
                window_end=report.window.end,
                dimension=dimension,
                previous_state=previous_state,
                current_state=current_state,
                message=(
                    f"ModelGuard entered {dimension.value}={current_state} for successful "
                    f"report {report.report_id}. Review the immutable monitoring report."
                ),
            )
            marker_path = self.root / "alerts" / f"{dimension.value}-{report.report_id}.json"
            marker = AlertMarker(notification=notification, send_result=None)
            if _create_if_absent(marker_path, canonical_json_bytes(marker) + b"\n"):
                claims.append((marker_path, notification))
        return claims

    def publish(
        self,
        report: MonitoringReport,
        *,
        alert_sink: AlertSink | None = None,
    ) -> PublishedReport:
        """Publish deterministically; alert only for a transition on a newer successful window."""

        self._ensure_root()
        json_bytes = canonical_json_bytes(report) + b"\n"
        html_bytes = render_offline_html(report).encode("utf-8")
        window_key = report.window.end.strftime("%Y%m%dT%H%M%SZ")
        history_root = self.root / "history" / window_key
        json_path = history_root / f"{report.report_id}.json"
        html_path = history_root / f"{report.report_id}.html"
        _create_if_absent(json_path, json_bytes)
        _create_if_absent(html_path, html_bytes)

        latest_path = self.root / "latest.json"
        lock_path = self.root / ".latest.lock"
        lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        lock_flags |= getattr(os, "O_NOFOLLOW", 0)
        lock_descriptor = os.open(lock_path, lock_flags, 0o600)
        claims: list[tuple[Path, AlertNotification]] = []
        latest_updated = False
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            previous = _read_report(latest_path)
            is_newer = previous is None or report.window.end > previous.window.end
            if is_newer:
                claims = self._claim_transition_markers(report, previous)
                _atomic_replace(latest_path, json_bytes)
                latest_updated = True
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)

        sink = alert_sink or UnconfiguredAlertSink()
        marker_paths: list[Path] = []
        for marker_path, notification in claims:
            result = sink.send(notification)
            completed_marker = AlertMarker(notification=notification, send_result=result)
            _atomic_replace(marker_path, canonical_json_bytes(completed_marker) + b"\n")
            marker_paths.append(marker_path)
        return PublishedReport(
            json_path=json_path,
            html_path=html_path,
            json_sha256=sha256_bytes(json_bytes),
            html_sha256=sha256_bytes(html_bytes),
            latest_updated=latest_updated,
            alert_markers=tuple(marker_paths),
        )

    def read_latest(self) -> MonitoringReport | None:
        self._ensure_root()
        return _read_report(self.root / "latest.json")


class RunStatusArtifact(StrictArtifactModel):
    status_schema_version: Literal["modelguard.monitor-run-status.v1"] = (
        "modelguard.monitor-run-status.v1"
    )
    latest_attempt_state: Literal["succeeded", "failed"]
    latest_attempt_at: AwareDatetime
    latest_success_at: AwareDatetime | None
    latest_report_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_reason: str | None

    @model_validator(mode="after")
    def validate_status(self) -> RunStatusArtifact:
        if self.latest_attempt_state == "succeeded":
            if self.latest_success_at != self.latest_attempt_at:
                raise ValueError("successful latest attempt must be the latest success")
            if self.latest_report_id is None or self.failure_reason is not None:
                raise ValueError("successful status requires report ID and no failure reason")
        elif self.failure_reason is None:
            raise ValueError("failed status requires a bounded failure reason")
        return self


class LocalRunStateStore:
    """Persist current-attempt failure separately from last successful report freshness."""

    def __init__(self, report_root: Path) -> None:
        self._root = report_root
        self._path = report_root / "run-status.json"
        self._lock_path = report_root / ".run-status.lock"

    def _read(self) -> RunStatusArtifact | None:
        if not self._path.exists():
            return None
        if self._path.is_symlink() or not self._path.is_file():
            raise OSError("run status path must be a regular file")
        return validate_strict_json_model(self._path.read_bytes(), RunStatusArtifact)

    def _write_if_current(self, status: RunStatusArtifact) -> bool:
        self._root.mkdir(parents=True, exist_ok=True)
        lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        lock_flags |= getattr(os, "O_NOFOLLOW", 0)
        lock_descriptor = os.open(self._lock_path, lock_flags, 0o600)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            current = self._read()
            candidate = status
            if current is not None:
                if status.latest_attempt_at < current.latest_attempt_at:
                    return False
                if status.latest_attempt_state == "failed":
                    candidate = status.model_copy(
                        update={
                            "latest_success_at": current.latest_success_at,
                            "latest_report_id": current.latest_report_id,
                        }
                    )
                payload = canonical_json_bytes(candidate) + b"\n"
                if status.latest_attempt_at == current.latest_attempt_at:
                    if canonical_json_bytes(current) + b"\n" != payload:
                        raise ValueError("same-time local run-status attempts conflict")
                    return False
            else:
                payload = canonical_json_bytes(candidate) + b"\n"
            _atomic_replace(self._path, payload)
            return True
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)

    def record_success(
        self,
        *,
        completed_at: datetime,
        report_id: str,
    ) -> bool:
        normalized = ensure_utc(completed_at, name="completed_at")
        return self._write_if_current(
            RunStatusArtifact(
                latest_attempt_state="succeeded",
                latest_attempt_at=normalized,
                latest_success_at=normalized,
                latest_report_id=report_id,
                failure_reason=None,
            )
        )

    def record_failure(self, *, attempted_at: datetime, reason: str) -> bool:
        normalized = ensure_utc(attempted_at, name="attempted_at")
        return self._write_if_current(
            RunStatusArtifact(
                latest_attempt_state="failed",
                latest_attempt_at=normalized,
                latest_success_at=None,
                latest_report_id=None,
                failure_reason=reason,
            )
        )

    def state_as_of(self, *, as_of: datetime, config: MonitoringConfig) -> RunState:
        status = self._read()
        if status is None:
            return RunState.NEVER_RUN
        return determine_run_state(
            current_attempt_failed=status.latest_attempt_state == "failed",
            latest_success_at=status.latest_success_at,
            as_of=ensure_utc(as_of, name="as_of"),
            stale_after=timedelta(seconds=config.stale_after_seconds),
        )
