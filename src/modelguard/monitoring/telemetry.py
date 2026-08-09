"""One bounded, redacted AWS EMF completion/count/freshness record per monitor run."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from modelguard.core.config import AppEnvironment
from modelguard.monitoring.report import MonitoringReport
from modelguard.monitoring.state import ensure_utc

EmfWriter = Callable[[str], None]
MONITOR_COMPLETION_METRIC_NAME = "MonitorCompletions"


def _stdout_writer(line: str) -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def build_monitor_completion_emf(
    report: MonitoringReport,
    *,
    as_of: datetime,
    environment: AppEnvironment,
) -> dict[str, Any]:
    """Build fixed dimensions and counts without IDs, features, secrets, or arbitrary versions."""

    normalized_as_of = ensure_utc(as_of, name="as_of")
    counts = report.records.counts
    latest_event = report.records.max_accepted_event_timestamp
    freshness_available = latest_event is not None
    freshness_seconds = (
        max((normalized_as_of - latest_event).total_seconds(), 0.0)
        if latest_event is not None
        else 0.0
    )
    report_freshness_seconds = max(
        (normalized_as_of - report.window.end).total_seconds(),
        0.0,
    )
    metrics: dict[str, tuple[float, str]] = {
        MONITOR_COMPLETION_METRIC_NAME: (1.0, "Count"),
        "RawRecords": (float(counts.raw), "Count"),
        "RejectedRecords": (float(counts.rejected), "Count"),
        "OutsideWindowRecords": (float(counts.outside_window), "Count"),
        "KnownNonTargetRecords": (float(counts.known_non_target), "Count"),
        "DuplicateRecords": (float(counts.duplicate), "Count"),
        "AcceptedTargetRecords": (float(counts.accepted_target), "Count"),
        "AcceptedEventFreshnessSeconds": (freshness_seconds, "Seconds"),
        "AcceptedEventFreshnessAvailable": (1.0 if freshness_available else 0.0, "Count"),
        "ReportFreshnessSeconds": (report_freshness_seconds, "Seconds"),
    }
    payload: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(normalized_as_of.timestamp() * 1_000),
            "CloudWatchMetrics": [
                {
                    "Namespace": "ModelGuardAI",
                    "Dimensions": [["Service", "Environment"]],
                    "Metrics": [
                        {"Name": name, "Unit": unit} for name, (_, unit) in metrics.items()
                    ],
                }
            ],
        },
        "Service": "monitor",
        "Environment": environment.value,
        "FreshnessSemantics": "accepted_event_time_not_row_delivery_lateness",
        "ReportFreshnessSemantics": "monitor_as_of_minus_finalized_window_end",
    }
    payload.update({name: value for name, (value, _) in metrics.items()})
    return payload


def emit_monitor_completion_emf(
    report: MonitoringReport,
    *,
    as_of: datetime,
    environment: AppEnvironment,
    writer: EmfWriter = _stdout_writer,
) -> None:
    """Emit exactly one strict compact JSON record."""

    payload = build_monitor_completion_emf(report, as_of=as_of, environment=environment)
    writer(json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True))
