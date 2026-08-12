"""Explicit-time/identity CLI success, idempotent rerun, and failure status tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pytest import CaptureFixture, MonkeyPatch

import modelguard.monitoring.cli as monitoring_cli
from modelguard.core.config import AppEnvironment, Settings
from modelguard.core.serialization import canonical_json_bytes
from modelguard.monitoring.events import EventIdentity
from modelguard.monitoring.persistence import LocalRunStateStore
from modelguard.monitoring.state import RunState
from modelguard.training.bundle import ValidatedBundleMetadata


def _args(
    *,
    metadata: ValidatedBundleMetadata,
    target: EventIdentity,
    event_directory: Path,
    report_directory: Path,
    as_of: str,
) -> list[str]:
    return [
        "run",
        "--window-end",
        "2026-01-01T01:00:00Z",
        "--as-of",
        as_of,
        "--bundle",
        str(metadata.path),
        "--event-dir",
        str(event_directory),
        "--report-dir",
        str(report_directory),
        "--minimum-accepted-events",
        "1",
        "--target-event-schema-version",
        target.event_schema_version,
        "--target-model-version",
        target.model_version,
        "--target-manifest-sha256",
        target.bundle_manifest_sha256,
        "--target-input-schema-version",
        target.input_schema_version,
    ]


def test_cli_uses_explicit_times_and_identity_and_exact_rerun_is_byte_stable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    event_directory = tmp_path / "events"
    event_directory.mkdir()
    event = monitoring_event_factory(
        1,
        datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
    )
    (event_directory / "events.jsonl").write_bytes(canonical_json_bytes(event) + b"\n")
    report_directory = tmp_path / "reports"
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        model_bundle_path=monitoring_metadata.path,
        active_model_version=monitoring_target.model_version,
    )
    monkeypatch.setattr(monitoring_cli, "load_settings", lambda: settings)
    arguments = _args(
        metadata=monitoring_metadata,
        target=monitoring_target,
        event_directory=event_directory,
        report_directory=report_directory,
        as_of="2026-01-01T01:10:00Z",
    )

    assert monitoring_cli.main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert monitoring_cli.main(arguments) == 0
    second = json.loads(capsys.readouterr().out)

    assert first["report_id"] == second["report_id"]
    assert first["json_sha256"] == second["json_sha256"]
    assert first["run_state"] == "succeeded"
    assert first["performance_state"] == "unknown"
    assert first["latest_updated"] is True
    assert second["latest_updated"] is False


def test_cli_rejects_pre_grace_run_and_persists_current_failure_separately(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        model_bundle_path=monitoring_metadata.path,
        active_model_version=monitoring_target.model_version,
    )
    monkeypatch.setattr(monitoring_cli, "load_settings", lambda: settings)
    event_directory = tmp_path / "events"
    event_directory.mkdir()
    report_directory = tmp_path / "reports"

    assert (
        monitoring_cli.main(
            _args(
                metadata=monitoring_metadata,
                target=monitoring_target,
                event_directory=event_directory,
                report_directory=report_directory,
                as_of="2026-01-01T01:09:59Z",
            )
        )
        == 1
    )
    assert "invalid_monitoring_contract" in capsys.readouterr().err
    assert (
        LocalRunStateStore(report_directory).state_as_of(
            as_of=datetime(2026, 1, 1, 1, 9, 59, tzinfo=UTC) + timedelta(hours=1),
            config=monitoring_cli.MonitoringConfig(),
        )
        is RunState.FAILED
    )


def test_cli_persists_invalid_monitoring_config_as_a_failed_attempt(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        model_bundle_path=monitoring_metadata.path,
        active_model_version=monitoring_target.model_version,
    )
    monkeypatch.setattr(monitoring_cli, "load_settings", lambda: settings)
    event_directory = tmp_path / "events"
    event_directory.mkdir()
    report_directory = tmp_path / "reports"
    invalid_config = tmp_path / "invalid-monitoring.json"
    invalid_config.write_text('{"contract_version":"invalid"}\n', encoding="utf-8")
    arguments = _args(
        metadata=monitoring_metadata,
        target=monitoring_target,
        event_directory=event_directory,
        report_directory=report_directory,
        as_of="2026-01-01T01:10:00Z",
    )
    arguments.extend(["--config", str(invalid_config)])

    assert monitoring_cli.main(arguments) == 1
    assert "invalid_monitoring_contract" in capsys.readouterr().err
    assert (
        LocalRunStateStore(report_directory).state_as_of(
            as_of=datetime(2026, 1, 1, 1, 10, tzinfo=UTC),
            config=monitoring_cli.MonitoringConfig(),
        )
        is RunState.FAILED
    )


def test_cli_normalizes_corrupt_gzip_and_persists_a_failed_attempt(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        model_bundle_path=monitoring_metadata.path,
        active_model_version=monitoring_target.model_version,
    )
    monkeypatch.setattr(monitoring_cli, "load_settings", lambda: settings)
    event_directory = tmp_path / "events"
    event_directory.mkdir()
    (event_directory / "corrupt.jsonl.gz").write_bytes(b"\x1f\x8b\x08\x00" + b"x" * 30)
    report_directory = tmp_path / "reports"

    assert (
        monitoring_cli.main(
            _args(
                metadata=monitoring_metadata,
                target=monitoring_target,
                event_directory=event_directory,
                report_directory=report_directory,
                as_of="2026-01-01T01:10:00Z",
            )
        )
        == 1
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "error: monitoring_runtime_failure\n"
    assert (
        LocalRunStateStore(report_directory).state_as_of(
            as_of=datetime(2026, 1, 1, 1, 10, tzinfo=UTC),
            config=monitoring_cli.MonitoringConfig(),
        )
        is RunState.FAILED
    )
