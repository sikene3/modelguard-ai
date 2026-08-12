#!/usr/bin/env python3
"""Run and compare deterministic Phase 11 monitoring/recovery evidence locally."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil

# Subprocess calls below use fixed local executables with argument arrays and no shell.
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from mlflow.exceptions import MlflowException
from PIL import Image, ImageDraw, ImageFont
from streamlit.testing.v1 import AppTest

from modelguard.api.main import create_app
from modelguard.core.config import AppEnvironment, EventSink, Settings
from modelguard.core.serialization import (
    StrictArtifactModel,
    canonical_json_bytes,
    load_strict_json,
    parse_strict_json_bytes,
    validate_strict_json_model,
)
from modelguard.core.telemetry import build_telemetry
from modelguard.dashboard.parsing import DashboardSnapshot, load_dashboard_snapshot
from modelguard.dashboard.repository import LocalDashboardRepository
from modelguard.inference.events import (
    EventSinkWriteResult,
    LocalEventWriteError,
    SerializedPredictionEvent,
)
from modelguard.monitoring.config import MonitoringConfig, load_monitoring_config
from modelguard.monitoring.drift import DriftSignal
from modelguard.monitoring.events import parse_utc_timestamp
from modelguard.monitoring.report import MonitoringReport
from modelguard.training.bundle import BundleIdentity, verify_bundle
from modelguard.training.config import TrainingConfig, load_training_config
from modelguard.training.workflow import generate_data_artifacts, train_from_artifacts

RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_BUNDLE = Path("artifacts/model-bundles/1.0.0")
DEFAULT_MONITORING_CONFIG = Path("configs/phase-07-monitoring.json")
DEFAULT_TRAINING_CONFIG = Path("configs/phase-02-training.json")
DEFAULT_EVIDENCE_ROOT = Path("artifacts/phase-11-evidence")
BASELINE_ROWS = 1_000
DRIFTED_ROWS = 1_000
INSUFFICIENT_ROWS = 50
CANDIDATE_MODEL_VERSION = "1.0.1"
SignalKind = Literal[
    "numeric_psi",
    "categorical_js_distance",
    "prediction_psi",
    "decision_js_distance",
]

EXPECTED_DEGRADED_SIGNALS: frozenset[tuple[SignalKind, str]] = frozenset(
    {
        ("numeric_psi", "amount"),
        ("numeric_psi", "velocity_1h"),
        ("numeric_psi", "distance_from_home_km"),
        ("numeric_psi", "device_risk_score"),
        ("numeric_psi", "merchant_risk_score"),
        ("categorical_js_distance", "is_new_device"),
        ("categorical_js_distance", "country_code"),
        ("categorical_js_distance", "device_type"),
        ("prediction_psi", "prediction_score"),
    }
)
EXPECTED_WARNING_SIGNALS: frozenset[tuple[SignalKind, str]] = frozenset(
    {("decision_js_distance", "locked_decision")}
)
EXPLICIT_DRIFT_CHANGES = {
    "amount": "min(25000, amount * 20 + 5000)",
    "velocity_1h": "min(30, velocity_1h + 15)",
    "distance_from_home_km": "min(1000, distance_from_home_km + 400)",
    "device_risk_score": "min(1.0, 0.8 + 0.2 * device_risk_score)",
    "merchant_risk_score": "min(1.0, 0.8 + 0.2 * merchant_risk_score)",
    "is_new_device": "true",
    "country_code": '"BR"',
    "device_type": '"tablet"',
}


class DemoEvidenceError(RuntimeError):
    """One Phase 11 evidence assertion did not hold."""


class LocalModelPointer(StrictArtifactModel):
    """Small local-only pointer used to demonstrate a controlled validated promotion."""

    pointer_schema_version: Literal["modelguard.phase-11-local-pointer.v1"] = (
        "modelguard.phase-11-local-pointer.v1"
    )
    active: BundleIdentity
    previous: BundleIdentity | None
    active_bundle_path: str
    promoted_at: str
    scope: Literal["local_demo_only"] = "local_demo_only"


@dataclass(frozen=True)
class DemoWindow:
    scenario: Literal["insufficient", "baseline", "drifted"]
    start: datetime
    end: datetime
    as_of: datetime


@dataclass(frozen=True)
class CommandEvidence:
    name: str
    argv: tuple[str, ...]
    started_at: str
    completed_at: str
    duration_seconds: float
    return_code: int
    stdout_path: str
    stderr_path: str
    stdout_sha256: str
    stderr_sha256: str


class RecordingLogger:
    """Keep bounded event names for the controlled in-process API exercises."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, object]]] = []

    def info(self, event: str, **fields: object) -> None:
        self.entries.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.entries.append(("warning", event, fields))

    def error(self, event: str, **fields: object) -> None:
        self.entries.append(("error", event, fields))


class ControlledOutageSink:
    """Deterministically inject the documented local producer outage boundary."""

    def __init__(self) -> None:
        self.emit_calls = 0
        self.closed = False

    async def emit(self, record: SerializedPredictionEvent) -> EventSinkWriteResult:
        del record
        self.emit_calls += 1
        raise LocalEventWriteError("controlled_phase_11_sink_outage")

    async def close(self) -> None:
        self.closed = True


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_now_text() -> str:
    return _utc_text(datetime.now(UTC))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("evidence write made no progress")
        offset += written


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError("evidence destination must be a regular non-symlink file")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, value: Any) -> None:
    payload = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    _atomic_write(path, payload)


def _json_object(path: Path) -> dict[str, Any]:
    value = load_strict_json(path)
    if not isinstance(value, dict):
        raise DemoEvidenceError(f"JSON evidence is not an object: {path.name}")
    return cast(dict[str, Any], value)


def build_demo_windows(anchor: datetime, config: MonitoringConfig) -> tuple[DemoWindow, ...]:
    """Build three adjacent, non-overlapping explicit UTC windows ending at ``anchor``."""

    if anchor.utcoffset() != timedelta(0):
        raise ValueError("anchor must be expressed in UTC")
    width = timedelta(seconds=config.window_seconds)
    grace = timedelta(seconds=config.finalization_grace_seconds)
    insufficient_end = anchor - 2 * width
    baseline_end = anchor - width
    windows = (
        DemoWindow(
            scenario="insufficient",
            start=insufficient_end - width,
            end=insufficient_end,
            as_of=insufficient_end + grace,
        ),
        DemoWindow(
            scenario="baseline",
            start=baseline_end - width,
            end=baseline_end,
            as_of=baseline_end + grace,
        ),
        DemoWindow(
            scenario="drifted",
            start=anchor - width,
            end=anchor,
            as_of=anchor + grace,
        ),
    )
    if windows[0].end != windows[1].start or windows[1].end != windows[2].start:
        raise ValueError("Phase 11 windows must be adjacent and non-overlapping")
    return windows


def _safe_subprocess_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        "ALB_ALLOWED_CIDR",
        "PREDICTION_BEARER_TOKEN",
        "PREDICTION_TOKEN_SSM_ARN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "APP_ENV": "local",
            "RUNTIME_COMPONENT": "monitor",
            "API_ACCESS_MODE": "local_open",
            "MODEL_BUNDLE_TRUSTED_ORIGIN": "true",
            "UV_CACHE_DIR": str((Path.cwd() / ".cache" / "uv").resolve()),
        }
    )
    return environment


def _run_command(
    *,
    name: str,
    argv: Sequence[str],
    evidence_directory: Path,
    commands: list[CommandEvidence],
) -> dict[str, Any]:
    started_at = _utc_now_text()
    started = time.perf_counter()
    # The executable is the current trusted Python interpreter; argv contains no secrets.
    result = subprocess.run(  # nosec B603
        list(argv),
        cwd=Path.cwd(),
        env=_safe_subprocess_environment(),
        check=False,
        capture_output=True,
    )
    duration = time.perf_counter() - started
    stdout_path = evidence_directory / f"{name}.stdout.jsonl"
    stderr_path = evidence_directory / f"{name}.stderr.txt"
    _atomic_write(stdout_path, result.stdout)
    _atomic_write(stderr_path, result.stderr)
    commands.append(
        CommandEvidence(
            name=name,
            argv=tuple(str(item) for item in argv),
            started_at=started_at,
            completed_at=_utc_now_text(),
            duration_seconds=round(duration, 6),
            return_code=result.returncode,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout_sha256=_sha256_bytes(result.stdout),
            stderr_sha256=_sha256_bytes(result.stderr),
        )
    )
    if result.returncode != 0:
        raise DemoEvidenceError(f"local command failed: {name}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise DemoEvidenceError(f"local command emitted no machine-readable result: {name}")
    parsed = parse_strict_json_bytes(lines[-1])
    if not isinstance(parsed, dict):
        raise DemoEvidenceError(f"local command result was not an object: {name}")
    return cast(dict[str, Any], parsed)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DemoEvidenceError(message)


def validate_scenario_report(
    report: MonitoringReport,
    *,
    window: DemoWindow,
    expected_accepted: int,
    expected_quality: str,
    expected_drift: str,
    minimum_accepted: int,
) -> None:
    """Validate the explicit window, reconciliation, and independent-state evidence."""

    _require(report.window.start == window.start, "report window start differed")
    _require(report.window.end == window.end, "report window end differed")
    _require(report.window.eligible_at == window.as_of, "report eligible/as-of differed")
    _require(report.states.run.value == "succeeded", "monitor run did not succeed")
    _require(report.states.data_quality.value == expected_quality, "data quality differed")
    _require(report.states.drift.value == expected_drift, "drift state differed")
    _require(report.states.performance.value == "unknown", "unlabeled performance was not unknown")
    _require(not report.performance.label_source_configured, "an unexpected label source was set")
    _require(report.performance.coverage is None, "unlabeled coverage was not null")
    _require(report.performance.metrics is None, "unlabeled performance metrics were emitted")
    counts = report.records.counts
    _require(counts.raw == expected_accepted, "raw count differed")
    _require(counts.accepted_target == expected_accepted, "accepted count differed")
    _require(
        counts.rejected
        == counts.outside_window
        == counts.known_non_target
        == counts.duplicate
        == 0,
        "isolated fixture had excluded or rejected records",
    )
    _require(
        counts.raw
        == counts.rejected
        + counts.outside_window
        + counts.known_non_target
        + counts.duplicate
        + counts.accepted_target,
        "record counts did not reconcile",
    )
    if expected_quality == "valid":
        _require(
            counts.accepted_target > minimum_accepted,
            "valid scenario did not retain headroom above the minimum",
        )


def _signal_thresholds(signal_kind: SignalKind, config: MonitoringConfig) -> tuple[float, float]:
    if signal_kind in {"numeric_psi", "prediction_psi"}:
        return config.psi_warning_threshold, config.psi_degraded_threshold
    return config.js_warning_threshold, config.js_degraded_threshold


def validate_expected_drift_metrics(
    report: MonitoringReport,
    config: MonitoringConfig,
) -> list[dict[str, Any]]:
    """Require the documented shifted fixture to breach every expected metric."""

    signals: dict[tuple[SignalKind, str], DriftSignal] = {
        (signal.kind, signal.name): signal for signal in report.drift.evaluation.signals
    }
    for key in EXPECTED_DEGRADED_SIGNALS:
        signal = signals.get(key)
        if signal is None:
            raise DemoEvidenceError(f"expected drift signal was absent: {key}")
        _require(
            signal.state.value == "degraded", f"expected degraded signal did not degrade: {key}"
        )
        if signal.value is None:
            raise DemoEvidenceError(f"expected degraded signal was unevaluable: {key}")
        _, degraded = _signal_thresholds(key[0], config)
        _require(signal.value >= degraded, f"degraded threshold was not breached: {key}")
    for key in EXPECTED_WARNING_SIGNALS:
        signal = signals.get(key)
        if signal is None:
            raise DemoEvidenceError(f"expected warning signal was absent: {key}")
        _require(signal.state.value == "warning", f"expected warning signal did not warn: {key}")
        if signal.value is None:
            raise DemoEvidenceError(f"expected warning signal was unevaluable: {key}")
        warning, degraded = _signal_thresholds(key[0], config)
        _require(
            warning <= signal.value < degraded,
            f"warning signal did not fall within its documented boundaries: {key}",
        )
    evidence: list[dict[str, Any]] = []
    for key in sorted(EXPECTED_DEGRADED_SIGNALS | EXPECTED_WARNING_SIGNALS):
        signal = signals[key]
        warning, degraded = _signal_thresholds(key[0], config)
        evidence.append(
            {
                "kind": signal.kind,
                "name": signal.name,
                "value": signal.value,
                "state": signal.state.value,
                "warning_threshold": warning,
                "degraded_threshold": degraded,
            }
        )
    return evidence


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _run_scenario(
    *,
    scenario: Literal["baseline", "drifted", "tiny"],
    window: DemoWindow,
    row_count: int,
    bundle: Path,
    monitoring_config_path: Path,
    report_root: Path,
    run_root: Path,
    commands: list[CommandEvidence],
) -> tuple[MonitoringReport, dict[str, Any]]:
    stage = "insufficient" if scenario == "tiny" else scenario
    stage_root = run_root / "scenarios" / stage
    event_root = stage_root / "events"
    stage_root.mkdir(parents=True, mode=0o700)
    window_end = _utc_text(window.end)
    as_of = _utc_text(window.as_of)
    fixture = _run_command(
        name=f"{stage}-fixture",
        argv=(
            sys.executable,
            "scripts/generate_monitoring_fixture.py",
            "--scenario",
            scenario,
            "--window-end",
            window_end,
            "--bundle",
            str(bundle),
            "--event-dir",
            str(event_root),
            "--row-count",
            str(row_count),
        ),
        evidence_directory=stage_root,
        commands=commands,
    )
    monitor = _run_command(
        name=f"{stage}-monitor",
        argv=(
            sys.executable,
            "-m",
            "modelguard.monitoring.cli",
            "run",
            "--config",
            str(monitoring_config_path),
            "--bundle",
            str(bundle),
            "--event-dir",
            str(event_root),
            "--report-dir",
            str(report_root),
            "--window-end",
            window_end,
            "--as-of",
            as_of,
        ),
        evidence_directory=stage_root,
        commands=commands,
    )
    report_path = Path(str(monitor.get("json_report", "")))
    html_path = Path(str(monitor.get("html_report", "")))
    _require(report_path.is_file(), f"{stage} JSON report was absent")
    _require(html_path.is_file(), f"{stage} HTML report was absent")
    report = validate_strict_json_model(report_path.read_bytes(), MonitoringReport)
    _require(fixture.get("row_count") == row_count, f"{stage} fixture row count differed")
    _require(monitor.get("report_id") == report.report_id, f"{stage} report ID differed")
    _require(monitor.get("json_sha256") == _sha256_file(report_path), f"{stage} JSON hash differed")
    _require(monitor.get("html_sha256") == _sha256_file(html_path), f"{stage} HTML hash differed")
    summary = {
        "scenario": stage,
        "window": {
            "semantics": report.window.semantics,
            "start": _utc_text(window.start),
            "end": window_end,
            "as_of": as_of,
            "eligible_at": _utc_text(report.window.eligible_at),
        },
        "states": report.states.model_dump(mode="json"),
        "records": report.records.counts.model_dump(mode="json"),
        "performance": {
            "label_source_configured": report.performance.label_source_configured,
            "coverage": report.performance.coverage,
            "metrics_present": report.performance.metrics is not None,
            "reason": report.performance.reason,
        },
        "identities": {
            "report_target": report.identities.event_carried_target.model_dump(mode="json"),
            "active_model": {
                "model_version": fixture["model_version"],
                "manifest_sha256": fixture["manifest_sha256"],
            },
            "active_matches_report_target": (
                fixture["model_version"] == report.identities.event_carried_target.model_version
                and fixture["manifest_sha256"]
                == report.identities.event_carried_target.bundle_manifest_sha256
            ),
        },
        "report": {
            "report_id": report.report_id,
            "json_path": _relative(report_path, run_root),
            "json_sha256": _sha256_file(report_path),
            "html_path": _relative(html_path, run_root),
            "html_sha256": _sha256_file(html_path),
        },
    }
    _write_json(stage_root / "summary.json", summary)
    return report, summary


def _dashboard_repository(report_root: Path, bundle: Path) -> LocalDashboardRepository:
    return LocalDashboardRepository(
        report_root=report_root,
        model_bundle_path=bundle,
        max_json_bytes=8 * 1024 * 1024,
        max_html_bytes=16 * 1024 * 1024,
    )


@contextmanager
def _temporary_environment(updates: Mapping[str, str]) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _dashboard_app_test(
    *,
    repository_root: Path,
    report_root: Path,
    bundle: Path,
    monitoring_config_path: Path,
    expected_states: tuple[str, str, str, str],
) -> dict[str, Any]:
    updates = {
        "APP_ENV": "test",
        "DASHBOARD_REPOSITORY": "local",
        "LOCAL_REPORT_DIR": str(report_root),
        "MODEL_BUNDLE_PATH": str(bundle),
        "ACTIVE_MODEL_VERSION": "1.0.0",
        "MONITORING_CONFIG_PATH": str(monitoring_config_path),
    }
    with _temporary_environment(updates):
        app = AppTest.from_file(
            str(repository_root / "src" / "modelguard" / "dashboard" / "app.py"),
            default_timeout=30,
        ).run()
    _require(not app.exception, "Streamlit in-process dashboard render raised an exception")
    _require([title.value for title in app.title] == ["ModelGuard AI"], "dashboard title differed")
    rendered = "\n".join(item.value for item in app.markdown)
    for state in expected_states:
        _require(f"mg-state {state}" in rendered, f"dashboard did not render state {state}")
    _require("Configured active model" in rendered, "dashboard active identity was absent")
    _require("Report target identity" in rendered, "dashboard report target was absent")
    return {
        "runner": "streamlit.testing.v1.AppTest",
        "network_socket_used": False,
        "exceptions": 0,
        "title": "ModelGuard AI",
        "state_card_classes": list(expected_states),
        "active_identity_section": True,
        "report_target_identity_section": True,
        "dataframe_count": len(app.dataframe),
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / filename
    if path.is_file():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _render_dashboard_snapshot(
    *,
    path: Path,
    snapshot: DashboardSnapshot,
    report: MonitoringReport,
    scenario: str,
    minimum_accepted: int,
) -> None:
    """Render a clearly labeled report-backed offline dashboard evidence image."""

    width, height = 1440, 1120
    image = Image.new("RGB", (width, height), "#f3f7fa")
    draw = ImageDraw.Draw(image)
    title_font = _font(38, bold=True)
    subtitle_font = _font(20)
    label_font = _font(16, bold=True)
    state_font = _font(26, bold=True)
    body_font = _font(16)
    small_font = _font(14)
    draw.text((70, 45), "ModelGuard AI", fill="#132238", font=title_font)
    draw.text(
        (70, 100),
        "OFFLINE REPORT-BACKED DASHBOARD SNAPSHOT",
        fill="#087f79",
        font=label_font,
    )
    draw.text(
        (70, 130),
        "Generated from validated latest.json via the real dashboard repository/parser; "
        "not a live-browser capture.",
        fill="#617084",
        font=small_font,
    )
    states = (
        ("MONITOR RUN", snapshot.run_state.value if snapshot.run_state else "unavailable"),
        ("DATA QUALITY", report.states.data_quality.value),
        ("INPUT & PREDICTION DRIFT", report.states.drift.value),
        ("LABEL-BACKED PERFORMANCE", report.states.performance.value),
    )
    colors = {
        "succeeded": "#1b9a73",
        "valid": "#1b9a73",
        "healthy": "#1b9a73",
        "degraded": "#d24b55",
        "unknown": "#758396",
        "insufficient_data": "#8559c7",
    }
    card_y = 185
    card_width = 310
    for index, (label, state) in enumerate(states):
        left = 70 + index * 335
        draw.rounded_rectangle(
            (left, card_y, left + card_width, card_y + 145),
            radius=16,
            fill="#ffffff",
            outline="#dbe3ea",
            width=2,
        )
        draw.rectangle(
            (left, card_y, left + card_width, card_y + 8),
            fill=colors.get(state, "#68788d"),
        )
        draw.text((left + 18, card_y + 28), label, fill="#66768b", font=small_font)
        draw.text(
            (left + 18, card_y + 65),
            state.replace("_", " ").title(),
            fill="#132238",
            font=state_font,
        )
    counts = report.records.counts
    draw.text((70, 375), "Window and accepted-target evidence", fill="#132238", font=state_font)
    lines = (
        f"Scenario: {scenario}",
        f"UTC half-open window: [{_utc_text(report.window.start)}, {_utc_text(report.window.end)})",
        f"Eligible/as-of: {_utc_text(report.window.eligible_at)}",
        f"Accepted target: {counts.accepted_target:,}  |  minimum: {minimum_accepted:,}  |  "
        f"headroom: {counts.accepted_target - minimum_accepted:+,}",
        f"Reconciliation: {counts.raw:,} raw = {counts.rejected:,} rejected + "
        f"{counts.outside_window:,} outside + {counts.known_non_target:,} non-target + "
        f"{counts.duplicate:,} duplicate + {counts.accepted_target:,} accepted",
    )
    for index, line in enumerate(lines):
        draw.text((90, 425 + 35 * index), line, fill="#263b52", font=body_font)
    target = report.identities.event_carried_target
    active = snapshot.active_model
    draw.text((70, 625), "Configured active model", fill="#132238", font=state_font)
    draw.text((735, 625), "Report target identity", fill="#132238", font=state_font)
    active_lines = (
        f"Version: {active.model_version if active else 'unavailable'}",
        f"Manifest: {(active.manifest_sha256[:24] + '…') if active else 'unavailable'}",
        f"Matches report target: {snapshot.active_matches_report_target}",
    )
    target_lines = (
        f"Version: {target.model_version}",
        f"Manifest: {target.bundle_manifest_sha256[:24]}…",
        f"Event schema: {target.event_schema_version}",
    )
    for index, line in enumerate(active_lines):
        draw.text((90, 680 + 33 * index), line, fill="#263b52", font=body_font)
    for index, line in enumerate(target_lines):
        draw.text((755, 680 + 33 * index), line, fill="#263b52", font=body_font)
    draw.text((70, 820), "Highest drift signals", fill="#132238", font=state_font)
    signals = sorted(
        report.drift.evaluation.signals,
        key=lambda signal: signal.value if signal.value is not None else -1.0,
        reverse=True,
    )[:5]
    for index, signal in enumerate(signals):
        value = "not evaluable" if signal.value is None else f"{signal.value:.4f}"
        line = f"{signal.name:<28} {signal.kind:<25} {value:<12} {signal.state.value}"
        draw.text((90, 870 + 34 * index), line, fill="#263b52", font=small_font)
    draw.text(
        (70, 1065),
        "No labels configured: performance remains unknown. Drift is not an accuracy claim.",
        fill="#617084",
        font=subtitle_font,
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    image.save(path, format="PNG", optimize=False)
    os.chmod(path, 0o600)


def _capture_dashboard_evidence(
    *,
    name: Literal["healthy", "degraded"],
    report_root: Path,
    bundle: Path,
    monitoring_config_path: Path,
    config: MonitoringConfig,
    run_root: Path,
    captured_at: datetime,
) -> dict[str, Any]:
    frozen_report_root = run_root / "dashboard" / f"{name}-repository"
    shutil.copytree(report_root, frozen_report_root)
    repository = _dashboard_repository(frozen_report_root, bundle)
    snapshot = load_dashboard_snapshot(
        repository,
        expected_active_model_version="1.0.0",
        monitoring_policy=config,
        captured_at=captured_at,
        history_limit=24,
    )
    report = snapshot.latest_report
    if report is None:
        raise DemoEvidenceError(f"{name} dashboard had no latest report")
    expected = (
        "succeeded",
        "valid",
        "healthy" if name == "healthy" else "degraded",
        "unknown",
    )
    actual = (
        snapshot.run_state.value if snapshot.run_state is not None else "unavailable",
        report.states.data_quality.value,
        report.states.drift.value,
        report.states.performance.value,
    )
    _require(actual == expected, f"{name} dashboard state sequence differed")
    active_model = snapshot.active_model
    if active_model is None:
        raise DemoEvidenceError(f"{name} active identity was unavailable")
    _require(snapshot.active_matches_report_target is True, f"{name} identities did not match")
    app_test = _dashboard_app_test(
        repository_root=Path.cwd(),
        report_root=frozen_report_root,
        bundle=bundle,
        monitoring_config_path=monitoring_config_path,
        expected_states=expected,
    )
    png_path = run_root / "dashboard" / f"{name}-dashboard-evidence.png"
    _render_dashboard_snapshot(
        path=png_path,
        snapshot=snapshot,
        report=report,
        scenario=name,
        minimum_accepted=config.minimum_accepted_events,
    )
    result = {
        "scenario": name,
        "captured_at": _utc_text(captured_at),
        "frozen_repository_path": _relative(frozen_report_root, run_root),
        "states": {
            "run": actual[0],
            "data_quality": actual[1],
            "drift": actual[2],
            "performance": actual[3],
        },
        "active_identity": active_model.model_dump(mode="json"),
        "report_target_identity": report.identities.event_carried_target.model_dump(mode="json"),
        "active_matches_report_target": snapshot.active_matches_report_target,
        "report_id": report.report_id,
        "app_test": app_test,
        "image": {
            "path": _relative(png_path, run_root),
            "sha256": _sha256_file(png_path),
            "dimensions": [1440, 1120],
            "capture_kind": "offline_report_backed_dashboard_snapshot",
        },
    }
    _write_json(run_root / "dashboard" / f"{name}.json", result)
    return result


def _validate_alert_marker(
    report_root: Path, report: MonitoringReport, run_root: Path
) -> dict[str, Any]:
    marker_path = report_root / "alerts" / f"drift-{report.report_id}.json"
    marker = _json_object(marker_path)
    notification = marker.get("notification")
    send_result = marker.get("send_result")
    _require(isinstance(notification, dict), "drift alert notification was absent")
    _require(isinstance(send_result, dict), "drift alert send result was absent")
    notification = cast(dict[str, Any], notification)
    send_result = cast(dict[str, Any], send_result)
    _require(notification.get("dimension") == "drift", "alert dimension differed")
    _require(notification.get("previous_state") == "healthy", "alert previous state differed")
    _require(notification.get("current_state") == "degraded", "alert current state differed")
    _require(send_result.get("status") == "not_configured", "local alert was misrepresented")
    return {
        "transition": "drift=healthy -> drift=degraded",
        "marker_path": _relative(marker_path, run_root),
        "marker_sha256": _sha256_file(marker_path),
        "send_status": "not_configured",
        "sns_configured": False,
        "cloudwatch_configured": False,
        "exactly_once_delivery_claimed": False,
        "interpretation": "local transition evidence only; no SNS or CloudWatch delivery claim",
    }


async def _exercise_sink_outage_async(bundle: Path) -> dict[str, Any]:
    settings = Settings.model_validate(
        {
            "app_env": AppEnvironment.TEST,
            "event_sink": EventSink.LOCAL,
            "model_bundle_path": bundle,
            "active_model_version": "1.0.0",
            "model_bundle_trusted_origin": True,
        }
    )
    sink = ControlledOutageSink()
    logger = RecordingLogger()
    telemetry = build_telemetry(settings)
    app = create_app(settings, telemetry=telemetry, logger=logger, event_sink=sink)
    request = _json_object(Path("examples/prediction-request.json"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://phase11.local"
        ) as client:
            ready = await client.get("/health/ready")
            prediction = await client.post("/v1/predict", json=request)
            metrics = (await client.get("/metrics")).text
    _require(ready.status_code == 200, "sink-outage service was not ready")
    _require(prediction.status_code == 200, "sink-outage prediction failed closed")
    _require(sink.emit_calls == 1 and sink.closed, "controlled outage sink lifecycle differed")
    _require(
        'modelguard_event_sink_operations_total{outcome="local_failed"} 1.0' in metrics,
        "local sink failure metric was absent",
    )
    _require(
        'modelguard_errors_total{kind="event_sink"} 1.0' in metrics,
        "event-sink error metric was absent",
    )
    events = [event for _, event, _ in logger.entries]
    _require(
        "prediction_event_local_persistence_failed" in events,
        "bounded sink failure log event was absent",
    )
    payload = cast(dict[str, Any], prediction.json())
    return {
        "scenario": "event_sink_outage",
        "injection": (
            "dependency-injected LocalEventWriteError on the real ASGI event-sink boundary"
        ),
        "network_socket_used": False,
        "service_ready_status": ready.status_code,
        "prediction_status": prediction.status_code,
        "prediction_model_version": payload.get("model_version"),
        "sink_emit_calls": sink.emit_calls,
        "sink_closed": sink.closed,
        "observed_metrics": [
            'modelguard_event_sink_operations_total{outcome="local_failed"} 1.0',
            'modelguard_errors_total{kind="event_sink"} 1.0',
        ],
        "classification": "operational_event_sink_outage",
        "model_degradation_claimed": False,
        "drift_evaluated": False,
        "performance_evaluated": False,
    }


def _exercise_sink_outage(bundle: Path, run_root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    result = asyncio.run(_exercise_sink_outage_async(bundle))
    result["duration_seconds"] = round(time.perf_counter() - started, 6)
    _write_json(run_root / "sink-outage" / "summary.json", result)
    return result


def _pointer_payload(pointer: LocalModelPointer) -> bytes:
    return canonical_json_bytes(pointer) + b"\n"


async def _verify_promoted_runtime_async(bundle: Path, version: str) -> dict[str, Any]:
    settings = Settings.model_validate(
        {
            "app_env": AppEnvironment.TEST,
            "event_sink": EventSink.DISABLED,
            "model_bundle_path": bundle,
            "active_model_version": version,
            "model_bundle_trusted_origin": True,
        }
    )
    logger = RecordingLogger()
    telemetry = build_telemetry(settings)
    app = create_app(settings, telemetry=telemetry, logger=logger)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://phase11.local"
        ) as client:
            ready = await client.get("/health/ready")
            version_response = await client.get("/version")
    _require(ready.status_code == 200, "promoted model did not become ready")
    _require(version_response.status_code == 200, "promoted model version endpoint failed")
    payload = cast(dict[str, Any], version_response.json())
    _require(payload.get("model_ready") is True, "promoted runtime did not report ready")
    _require(payload.get("model_version") == version, "promoted runtime served a different version")
    return {
        "network_socket_used": False,
        "ready_status": ready.status_code,
        "version_status": version_response.status_code,
        "served_model_version": payload.get("model_version"),
        "served_manifest_sha256": payload.get("manifest_sha256"),
    }


def _run_validated_promotion(
    *,
    current_bundle: Path,
    training_config_path: Path,
    run_root: Path,
    promoted_at: datetime,
) -> dict[str, Any]:
    """Train, verify, atomically point to, and readiness-check a local candidate bundle."""

    recovery_root = run_root / "recovery"
    recovery_root.mkdir(parents=True, mode=0o700)
    current = verify_bundle(current_bundle, trusted_origin=True)
    base_config = load_training_config(training_config_path)
    _require(base_config.model_version != CANDIDATE_MODEL_VERSION, "candidate version was not new")
    candidate_config = base_config.model_copy(update={"model_version": CANDIDATE_MODEL_VERSION})
    _require(isinstance(candidate_config, TrainingConfig), "candidate config validation failed")
    candidate_config_path = recovery_root / "candidate-training-config.json"
    _write_json(candidate_config_path, candidate_config.model_dump(mode="json", by_alias=True))
    candidate_output = recovery_root / "candidate-artifacts"
    training_started_at = _utc_now_text()
    training_started = time.perf_counter()
    temporary_root = Path(tempfile.mkdtemp(prefix="modelguard-phase11-promotion-"))
    temporary_output = temporary_root / "candidate-output"
    try:
        generate_data_artifacts(candidate_config_path, temporary_output)
        trained = train_from_artifacts(candidate_config_path, temporary_output, Path.cwd())
        training_duration = time.perf_counter() - training_started
        shutil.copytree(temporary_output, candidate_output)
        temporary_tracking = temporary_root / "mlruns"
        if temporary_tracking.is_dir():
            shutil.copytree(temporary_tracking, recovery_root / "mlruns")
    finally:
        shutil.rmtree(temporary_root)
    candidate_bundle = candidate_output / "model-bundles" / CANDIDATE_MODEL_VERSION
    verified = verify_bundle(candidate_bundle, trusted_origin=True)
    _require(
        verified.metadata.identity.model_version == CANDIDATE_MODEL_VERSION,
        "candidate identity differed after verification",
    )
    before = LocalModelPointer(
        active=current.metadata.identity,
        previous=None,
        active_bundle_path=str(current_bundle.resolve()),
        promoted_at=_utc_text(promoted_at - timedelta(seconds=1)),
    )
    before_path = recovery_root / "pointer-before.json"
    _atomic_write(before_path, _pointer_payload(before))
    after = LocalModelPointer(
        active=verified.metadata.identity,
        previous=current.metadata.identity,
        active_bundle_path=str(candidate_bundle.resolve()),
        promoted_at=_utc_text(promoted_at),
    )
    active_pointer_path = recovery_root / "active-pointer.json"
    _atomic_write(active_pointer_path, _pointer_payload(after))
    readback = LocalModelPointer.model_validate(load_strict_json(active_pointer_path))
    _require(readback == after, "promoted local pointer readback differed")
    _require(readback.previous == current.metadata.identity, "previous identity was not retained")
    runtime = asyncio.run(
        _verify_promoted_runtime_async(Path(readback.active_bundle_path), CANDIDATE_MODEL_VERSION)
    )
    _require(
        runtime["served_manifest_sha256"] == verified.metadata.identity.manifest_sha256,
        "promoted runtime manifest differed from the pointer",
    )
    result = {
        "story": "validated_local_model_promotion",
        "scope": "local_demo_only",
        "causally_related_to_drift": False,
        "automatic_retraining": False,
        "automatic_promotion": False,
        "accuracy_improvement_claimed": False,
        "selection_basis": (
            "bundle integrity, trusted-origin verification, identity, and readiness only"
        ),
        "training": {
            "started_at": training_started_at,
            "completed_at": _utc_now_text(),
            "duration_seconds": round(training_duration, 6),
            "candidate_config_path": _relative(candidate_config_path, run_root),
            "candidate_bundle_path": _relative(candidate_bundle, run_root),
            "mlflow_run_id": trained.mlflow_run_id,
            "nondeterministic_fields": ["timestamps", "mlflow_run_id", "manifest_sha256"],
        },
        "before": before.model_dump(mode="json"),
        "after": after.model_dump(mode="json"),
        "pointer": {
            "path": _relative(active_pointer_path, run_root),
            "sha256": _sha256_file(active_pointer_path),
            "atomic_readback_valid": True,
            "previous_identity_retained": True,
        },
        "candidate_verification": {
            "status": "verified",
            "trusted_origin_confirmed": True,
            "model_version": verified.metadata.identity.model_version,
            "manifest_sha256": verified.metadata.identity.manifest_sha256,
            "smoke_score_finite": 0.0 <= verified.smoke_score <= 1.0,
            "metric_comparison_used_for_promotion": False,
        },
        "runtime": runtime,
    }
    _write_json(recovery_root / "summary.json", result)
    return result


def _aws_boundary(repository_root: Path) -> dict[str, Any]:
    status = _json_object(repository_root / "tasks" / "phase_status.json")
    phase_10 = status.get("phase_10")
    _require(isinstance(phase_10, dict), "Phase 10 status was absent")
    phase_10 = cast(dict[str, Any], phase_10)
    destroyed = phase_10.get("live_deployment_destroyed") is True
    residuals = phase_10.get("disposable_demo_resource_residuals")
    _require(destroyed and residuals == 0, "repository status does not record AWS teardown")
    return {
        "phase_11_aws_demo": "not_run",
        "reason": "demo environment was recorded destroyed before Phase 11",
        "status_source": "tasks/phase_status.json",
        "source_phase": "phase_10",
        "recorded_live_deployment_destroyed": destroyed,
        "recorded_disposable_demo_resource_residuals": residuals,
        "live_inventory_reverified_in_this_run": False,
        "aws_mutations_in_this_run": 0,
        "sns_cloudwatch_evidence": (
            "not configured locally; Phase 10 historical live evidence is not relabeled as "
            "Phase 11 healthy/degraded alert delivery"
        ),
    }


def _commands_json(commands: Sequence[CommandEvidence], run_root: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for command in commands:
        value = {
            "name": command.name,
            "argv": list(command.argv),
            "started_at": command.started_at,
            "completed_at": command.completed_at,
            "duration_seconds": command.duration_seconds,
            "return_code": command.return_code,
            "stdout_path": _relative(Path(command.stdout_path), run_root),
            "stderr_path": _relative(Path(command.stderr_path), run_root),
            "stdout_sha256": command.stdout_sha256,
            "stderr_sha256": command.stderr_sha256,
        }
        values.append(value)
    return values


def run_local_demo(args: argparse.Namespace) -> dict[str, Any]:
    repository_root = Path.cwd().resolve()
    bundle = args.bundle.resolve()
    monitoring_config_path = args.monitoring_config.resolve()
    training_config_path = args.training_config.resolve()
    config = load_monitoring_config(monitoring_config_path)
    anchor = parse_utc_timestamp(args.anchor, name="anchor")
    now = datetime.now(UTC)
    windows = build_demo_windows(anchor, config)
    insufficient_window, baseline_window, drifted_window = windows
    _require(drifted_window.as_of <= now, "anchor plus finalization grace is in the future")
    _require(
        now - baseline_window.as_of < timedelta(seconds=config.stale_after_seconds),
        "anchor is too old for a healthy dashboard run-state capture",
    )
    _require(config.minimum_accepted_events < BASELINE_ROWS, "baseline lacks sample headroom")
    _require(
        config.minimum_accepted_events < DRIFTED_ROWS, "drifted scenario lacks sample headroom"
    )
    _require(
        config.minimum_accepted_events > INSUFFICIENT_ROWS, "tiny scenario is not insufficient"
    )
    if RUN_ID_PATTERN.fullmatch(args.run_id) is None:
        raise ValueError("run-id must match ^[a-z0-9][a-z0-9-]{0,63}$")
    evidence_root = args.evidence_root.resolve()
    run_root = evidence_root / args.run_id
    if run_root.exists() or run_root.is_symlink():
        raise FileExistsError(f"Phase 11 run root already exists: {run_root}")
    run_root.mkdir(parents=True, mode=0o700)
    os.chmod(run_root, 0o700)
    commands: list[CommandEvidence] = []
    started_at = _utc_now_text()
    started = time.perf_counter()
    shared_report_root = run_root / "monitoring" / "transition-reports"
    insufficient_report_root = run_root / "monitoring" / "insufficient-reports"

    baseline_report, baseline = _run_scenario(
        scenario="baseline",
        window=baseline_window,
        row_count=BASELINE_ROWS,
        bundle=bundle,
        monitoring_config_path=monitoring_config_path,
        report_root=shared_report_root,
        run_root=run_root,
        commands=commands,
    )
    validate_scenario_report(
        baseline_report,
        window=baseline_window,
        expected_accepted=BASELINE_ROWS,
        expected_quality="valid",
        expected_drift="healthy",
        minimum_accepted=config.minimum_accepted_events,
    )
    baseline["samples"] = {
        "minimum_accepted": config.minimum_accepted_events,
        "accepted": BASELINE_ROWS,
        "headroom": BASELINE_ROWS - config.minimum_accepted_events,
    }
    _write_json(run_root / "scenarios" / "baseline" / "summary.json", baseline)
    healthy_dashboard = _capture_dashboard_evidence(
        name="healthy",
        report_root=shared_report_root,
        bundle=bundle,
        monitoring_config_path=monitoring_config_path,
        config=config,
        run_root=run_root,
        captured_at=baseline_window.as_of + timedelta(seconds=1),
    )

    drifted_report, drifted = _run_scenario(
        scenario="drifted",
        window=drifted_window,
        row_count=DRIFTED_ROWS,
        bundle=bundle,
        monitoring_config_path=monitoring_config_path,
        report_root=shared_report_root,
        run_root=run_root,
        commands=commands,
    )
    validate_scenario_report(
        drifted_report,
        window=drifted_window,
        expected_accepted=DRIFTED_ROWS,
        expected_quality="valid",
        expected_drift="degraded",
        minimum_accepted=config.minimum_accepted_events,
    )
    _require(
        baseline_report.window.end <= drifted_report.window.start,
        "baseline and drifted windows overlap",
    )
    drifted["samples"] = {
        "minimum_accepted": config.minimum_accepted_events,
        "accepted": DRIFTED_ROWS,
        "headroom": DRIFTED_ROWS - config.minimum_accepted_events,
    }
    drifted["explicit_feature_changes"] = EXPLICIT_DRIFT_CHANGES
    drifted["expected_breached_metrics"] = validate_expected_drift_metrics(drifted_report, config)
    _write_json(run_root / "scenarios" / "drifted" / "summary.json", drifted)
    degraded_dashboard = _capture_dashboard_evidence(
        name="degraded",
        report_root=shared_report_root,
        bundle=bundle,
        monitoring_config_path=monitoring_config_path,
        config=config,
        run_root=run_root,
        captured_at=drifted_window.as_of + timedelta(seconds=1),
    )
    alert = _validate_alert_marker(shared_report_root, drifted_report, run_root)
    _write_json(run_root / "alerts" / "summary.json", alert)

    insufficient_report, insufficient = _run_scenario(
        scenario="tiny",
        window=insufficient_window,
        row_count=INSUFFICIENT_ROWS,
        bundle=bundle,
        monitoring_config_path=monitoring_config_path,
        report_root=insufficient_report_root,
        run_root=run_root,
        commands=commands,
    )
    validate_scenario_report(
        insufficient_report,
        window=insufficient_window,
        expected_accepted=INSUFFICIENT_ROWS,
        expected_quality="insufficient_data",
        expected_drift="unknown",
        minimum_accepted=config.minimum_accepted_events,
    )
    insufficient["interpretation"] = {
        "classification": "insufficient_monitoring_data",
        "model_degradation_claimed": False,
        "accuracy_decrease_claimed": False,
    }
    _write_json(run_root / "scenarios" / "insufficient" / "summary.json", insufficient)

    sink_outage = _exercise_sink_outage(bundle, run_root)
    recovery = _run_validated_promotion(
        current_bundle=bundle,
        training_config_path=training_config_path,
        run_root=run_root,
        promoted_at=drifted_window.as_of,
    )
    aws = _aws_boundary(repository_root)
    completed_at = _utc_now_text()
    total_duration = round(time.perf_counter() - started, 6)
    summary = {
        "schema_version": "modelguard.phase-11-local-demo-evidence.v1",
        "status": "passed",
        "run_id": args.run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": total_duration,
        "anchor": _utc_text(anchor),
        "model_bundle": {
            "path": str(bundle),
            "model_version": baseline_report.identities.event_carried_target.model_version,
            "manifest_sha256": (
                baseline_report.identities.event_carried_target.bundle_manifest_sha256
            ),
        },
        "monitoring_config": {
            "path": str(monitoring_config_path),
            "minimum_accepted_events": config.minimum_accepted_events,
            "window_seconds": config.window_seconds,
            "finalization_grace_seconds": config.finalization_grace_seconds,
        },
        "healthy_to_degraded": {
            "windows_non_overlapping": True,
            "latest_advanced_from": baseline_report.report_id,
            "latest_advanced_to": drifted_report.report_id,
            "baseline": baseline,
            "drifted": drifted,
            "dashboard_transition": [healthy_dashboard, degraded_dashboard],
            "alert": alert,
        },
        "insufficient_data": insufficient,
        "event_sink_outage": sink_outage,
        "controlled_recovery": recovery,
        "aws": aws,
        "claims": {
            "accuracy_decrease_claimed": False,
            "drift_caused_performance_change_claimed": False,
            "recovery_fixed_drift_claimed": False,
            "real_customer_data_used": False,
            "malicious_traffic_used": False,
        },
        "commands": _commands_json(commands, run_root),
        "teardown": {
            "status": "verified",
            "long_running_local_processes_started": 0,
            "network_listeners_started": 0,
            "asgi_lifespans_closed": True,
            "controlled_outage_sink_closed": sink_outage["sink_closed"],
            "deliberately_broken_deployment_active": False,
            "aws_environment_started": False,
            "aws_environment_left_running": False,
        },
        "nondeterminism": {
            "expected": [
                "wall-clock start/completion timestamps",
                "measured command/training/ASGI durations",
                "MLflow candidate run ID",
                "candidate bundle creation timestamp and derived manifest SHA-256",
            ],
            "deterministic_contracts": [
                "fixture rows and event IDs for a fixed anchor",
                "monitoring report IDs and JSON/HTML hashes for a fixed bundle/config/anchor",
                "state sequences, accepted counts, headroom, and breached drift metrics",
            ],
        },
    }
    summary_path = run_root / "summary.json"
    _write_json(summary_path, summary)
    _write_json(run_root / "commands.json", summary["commands"])
    return {
        "status": "passed",
        "run_id": args.run_id,
        "summary": str(summary_path),
        "duration_seconds": total_duration,
        "states": {
            "baseline": baseline["states"],
            "drifted": drifted["states"],
            "insufficient": insufficient["states"],
        },
    }


def _stable_run_projection(summary: Mapping[str, Any]) -> dict[str, Any]:
    transition = cast(Mapping[str, Any], summary["healthy_to_degraded"])
    baseline = cast(Mapping[str, Any], transition["baseline"])
    drifted = cast(Mapping[str, Any], transition["drifted"])
    insufficient = cast(Mapping[str, Any], summary["insufficient_data"])
    alert = cast(Mapping[str, Any], transition["alert"])
    dashboard = cast(Sequence[Mapping[str, Any]], transition["dashboard_transition"])
    sink = cast(Mapping[str, Any], summary["event_sink_outage"])
    return {
        "anchor": summary["anchor"],
        "model_bundle": summary["model_bundle"],
        "monitoring_config": summary["monitoring_config"],
        "baseline": {
            "window": baseline["window"],
            "states": baseline["states"],
            "records": baseline["records"],
            "samples": baseline["samples"],
            "report": baseline["report"],
        },
        "drifted": {
            "window": drifted["window"],
            "states": drifted["states"],
            "records": drifted["records"],
            "samples": drifted["samples"],
            "report": drifted["report"],
            "expected_breached_metrics": drifted["expected_breached_metrics"],
        },
        "insufficient": {
            "window": insufficient["window"],
            "states": insufficient["states"],
            "records": insufficient["records"],
            "report": insufficient["report"],
        },
        "alert_transition": alert["transition"],
        "alert_send_status": alert["send_status"],
        "alert_marker_sha256": alert["marker_sha256"],
        "dashboard_transition": [
            {
                "scenario": item["scenario"],
                "states": item["states"],
                "report_id": item["report_id"],
                "active_identity": item["active_identity"],
                "report_target_identity": item["report_target_identity"],
                "active_matches_report_target": item["active_matches_report_target"],
                "app_test": item["app_test"],
                "image": item["image"],
            }
            for item in dashboard
        ],
        "sink_outage": {
            "prediction_status": sink["prediction_status"],
            "classification": sink["classification"],
            "model_degradation_claimed": sink["model_degradation_claimed"],
        },
        "claims": summary["claims"],
        "teardown": summary["teardown"],
    }


def compare_local_runs(args: argparse.Namespace) -> dict[str, Any]:
    first = _json_object(args.first.resolve())
    second = _json_object(args.second.resolve())
    _require(first.get("status") == second.get("status") == "passed", "both runs must pass")
    first_projection = _stable_run_projection(first)
    second_projection = _stable_run_projection(second)
    _require(first_projection == second_projection, "deterministic Phase 11 projections differed")
    comparison = {
        "schema_version": "modelguard.phase-11-repeatability-evidence.v1",
        "status": "passed",
        "first_run_id": first.get("run_id"),
        "second_run_id": second.get("run_id"),
        "same_anchor": first.get("anchor") == second.get("anchor"),
        "stable_projection_sha256": _sha256_bytes(canonical_json_bytes(first_projection)),
        "monitoring_report_ids_and_hashes_match": True,
        "states_counts_headroom_and_breaches_match": True,
        "expected_nondeterminism": first.get("nondeterminism", {}).get("expected", []),
        "different_candidate_manifest_allowed": (
            first.get("controlled_recovery", {})
            .get("candidate_verification", {})
            .get("manifest_sha256")
            != second.get("controlled_recovery", {})
            .get("candidate_verification", {})
            .get("manifest_sha256")
        ),
    }
    _write_json(args.output.resolve(), comparison)
    return comparison


def verify_local_teardown(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = args.summary.resolve()
    summary = _json_object(summary_path)
    teardown = summary.get("teardown")
    _require(isinstance(teardown, dict), "teardown evidence was absent")
    teardown = cast(dict[str, Any], teardown)
    _require(teardown.get("status") == "verified", "local teardown was not verified")
    _require(teardown.get("long_running_local_processes_started") == 0, "processes were left")
    _require(teardown.get("network_listeners_started") == 0, "listeners were left")
    _require(teardown.get("asgi_lifespans_closed") is True, "ASGI lifespans remained open")
    _require(
        teardown.get("deliberately_broken_deployment_active") is False,
        "a broken deployment remained active",
    )
    _require(teardown.get("aws_environment_started") is False, "AWS was unexpectedly started")
    result = {
        "schema_version": "modelguard.phase-11-local-teardown-verification.v1",
        "status": "passed",
        "summary": str(summary_path),
        "checked_at": _utc_now_text(),
        "long_running_processes": 0,
        "network_listeners": 0,
        "broken_deployment_active": False,
        "aws_environment_started": False,
    }
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run-local", help="execute one complete local Phase 11 evidence run"
    )
    run.add_argument("--run-id", required=True)
    run.add_argument("--anchor", required=True, help="explicit finalized UTC end ending in Z")
    run.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    run.add_argument("--monitoring-config", type=Path, default=DEFAULT_MONITORING_CONFIG)
    run.add_argument("--training-config", type=Path, default=DEFAULT_TRAINING_CONFIG)
    run.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)

    compare = subparsers.add_parser("compare-local-runs", help="compare two completed local runs")
    compare.add_argument("--first", type=Path, required=True)
    compare.add_argument("--second", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)

    teardown = subparsers.add_parser(
        "verify-local-teardown",
        help="verify one run's explicit no-long-running-resource closure evidence",
    )
    teardown.add_argument("--summary", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    args = _parser().parse_args(argv)
    try:
        if args.command == "run-local":
            result = run_local_demo(args)
        elif args.command == "compare-local-runs":
            result = compare_local_runs(args)
        else:
            result = verify_local_teardown(args)
    except (
        DemoEvidenceError,
        FileExistsError,
        MlflowException,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "category": type(error).__name__,
                    "reason": str(error),
                },
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
