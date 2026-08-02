"""Pure presentation helpers over already-computed monitoring evidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.drift import DriftSignal
from modelguard.monitoring.report import MonitoringReport


@dataclass(frozen=True)
class DriftFeatureRow:
    feature: str
    metric: str
    score: float | None
    warning_threshold: float | None
    degraded_threshold: float | None
    severity: str
    reason: str


def format_utc(value: datetime | None) -> str:
    if value is None:
        return "Unavailable"
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def format_duration(seconds: float | None) -> str:
    """Format an exact measured age compactly without implying live updates."""

    if seconds is None:
        return "Unavailable"
    total = max(int(seconds), 0)
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def readable_code(value: str) -> str:
    return value.replace("_", " ")


def metric_name(signal: DriftSignal) -> str:
    return {
        "numeric_psi": "PSI",
        "categorical_js_distance": "Jensen-Shannon distance",
        "prediction_psi": "Prediction PSI",
        "decision_js_distance": "Decision JS distance",
    }[signal.kind]


def thresholds_for_signal(
    signal: DriftSignal,
    policy: MonitoringConfig | None,
) -> tuple[float | None, float | None]:
    if policy is None:
        return None, None
    if signal.kind in {"numeric_psi", "prediction_psi"}:
        return policy.psi_warning_threshold, policy.psi_degraded_threshold
    return policy.js_warning_threshold, policy.js_degraded_threshold


def top_drifting_features(
    report: MonitoringReport,
    policy: MonitoringConfig | None,
    *,
    limit: int = 6,
) -> tuple[DriftFeatureRow, ...]:
    """Rank report-computed input signals; never recalculate a drift score or state."""

    if limit < 1:
        raise ValueError("top feature limit must be positive")
    severity_rank = {"degraded": 3, "warning": 2, "unknown": 1, "healthy": 0}
    rows: list[tuple[float, DriftFeatureRow]] = []
    for signal in report.drift.evaluation.signals:
        if signal.kind not in {"numeric_psi", "categorical_js_distance"}:
            continue
        warning, degraded = thresholds_for_signal(signal, policy)
        normalized = (
            signal.value / degraded
            if signal.value is not None and degraded is not None and degraded > 0.0
            else signal.value or 0.0
        )
        row = DriftFeatureRow(
            feature=signal.name,
            metric=metric_name(signal),
            score=signal.value,
            warning_threshold=warning,
            degraded_threshold=degraded,
            severity=signal.state.value,
            reason=signal.reason,
        )
        rows.append((normalized, row))
    rows.sort(
        key=lambda item: (
            severity_rank[item[1].severity],
            item[0],
            item[1].feature,
        ),
        reverse=True,
    )
    return tuple(row for _, row in rows[:limit])


def comparable_signals(
    report: MonitoringReport,
    *,
    kind: str,
) -> tuple[DriftSignal, ...]:
    return tuple(
        signal
        for signal in report.drift.evaluation.signals
        if signal.kind == kind
        and len(signal.universe) == len(signal.baseline_proportions)
        and len(signal.universe) == len(signal.current_proportions)
        and bool(signal.universe)
    )


def distribution_comparison(signal: DriftSignal) -> pd.DataFrame:
    if not (
        len(signal.universe) == len(signal.baseline_proportions) == len(signal.current_proportions)
    ):
        raise ValueError("signal does not contain comparable report distributions")
    labels = [
        f"{index + 1}. {label}" if signal.universe.count(label) > 1 else label
        for index, label in enumerate(signal.universe)
    ]
    return pd.DataFrame(
        {
            "Bucket": labels,
            "Baseline": signal.baseline_proportions,
            "Current window": signal.current_proportions,
        }
    ).set_index("Bucket")


def _history_signal(
    reports: Sequence[MonitoringReport],
    *,
    name: str,
) -> pd.DataFrame:
    rows: list[dict[str, str | float]] = []
    for report in reports:
        signal = next(
            (item for item in report.drift.evaluation.signals if item.name == name),
            None,
        )
        if signal is None or len(signal.universe) != len(signal.current_proportions):
            continue
        window_label = f"{format_utc(report.window.end)} · {report.report_id[:6]}"
        for bucket, proportion in zip(
            signal.universe,
            signal.current_proportions,
            strict=True,
        ):
            rows.append(
                {
                    "Window": window_label,
                    "Bucket": bucket,
                    "Proportion": proportion,
                }
            )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    return frame.pivot(index="Window", columns="Bucket", values="Proportion")


def prediction_score_trend(reports: Sequence[MonitoringReport]) -> pd.DataFrame:
    """Return exact report score-bin proportions across windows."""

    return _history_signal(reports, name="prediction_score")


def decision_trend(reports: Sequence[MonitoringReport]) -> pd.DataFrame:
    """Return exact report decision proportions across windows."""

    frame = _history_signal(reports, name="locked_decision")
    desired = [column for column in ("low_risk", "high_risk") if column in frame.columns]
    return frame.loc[:, desired] if desired else pd.DataFrame()


def comparable_report_history(
    reports: Sequence[MonitoringReport],
    *,
    reference: MonitoringReport,
) -> tuple[MonitoringReport, ...]:
    """Keep only reports whose prediction distributions have the same frozen identity."""

    reference_identities = reference.identities
    return tuple(
        report
        for report in reports
        if report.identities.event_carried_target == reference_identities.event_carried_target
        and report.identities.baseline_derived_from_verified_manifest
        == reference_identities.baseline_derived_from_verified_manifest
        and report.identities.monitoring_config_version
        == reference_identities.monitoring_config_version
        and report.identities.monitoring_config_hash == reference_identities.monitoring_config_hash
    )
