"""Phase 06 repository, strict parsing, freshness, and presentation tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from modelguard.core.config import AppEnvironment
from modelguard.core.serialization import (
    canonical_json_bytes,
    validate_strict_json_model,
    write_json,
)
from modelguard.dashboard.app import _state_card
from modelguard.dashboard.config import DashboardRepositoryMode, DashboardSettings
from modelguard.dashboard.parsing import (
    ArtifactAvailability,
    load_dashboard_snapshot,
    parse_monitoring_report,
)
from modelguard.dashboard.presentation import (
    comparable_report_history,
    comparable_signals,
    decision_trend,
    distribution_comparison,
    prediction_score_trend,
    top_drifting_features,
)
from modelguard.dashboard.repository import (
    DashboardRepositoryError,
    LocalDashboardRepository,
    RawArtifact,
    S3DashboardRepository,
)
from modelguard.inference.events import PredictionEventV1
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.persistence import RunStatusArtifact
from modelguard.monitoring.service import LocalMonitoringRunSpec, run_local_monitoring
from modelguard.monitoring.state import RunState
from modelguard.training.bundle import ValidatedBundleMetadata


@dataclass(frozen=True)
class DashboardArtifacts:
    report_root: Path
    policy: MonitoringConfig
    completed_at: datetime
    metadata: ValidatedBundleMetadata


def test_dashboard_settings_are_local_first_and_require_private_s3_inputs() -> None:
    local = DashboardSettings(_env_file=None)
    assert local.dashboard_repository is DashboardRepositoryMode.LOCAL

    with pytest.raises(ValidationError, match="requires DASHBOARD_REPOSITORY=s3"):
        DashboardSettings(_env_file=None, app_env=AppEnvironment.AWS)
    with pytest.raises(ValidationError, match="requires MODEL_BUCKET and REPORT_BUCKET"):
        DashboardSettings(_env_file=None, dashboard_repository=DashboardRepositoryMode.S3)

    aws = DashboardSettings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        dashboard_repository=DashboardRepositoryMode.S3,
        model_bucket="private-models",
        report_bucket="private-reports",
        aws_health_required=True,
        dashboard_source_region="us-east-1",
        dashboard_monitor_log_group="/modelguard-ai/demo/monitor",
        dashboard_s3_endpoint_url="https://s3.us-east-1.amazonaws.com",
        dashboard_cloudwatch_endpoint_url="https://monitoring.us-east-1.amazonaws.com",
        dashboard_logs_endpoint_url="https://logs.us-east-1.amazonaws.com",
    )
    assert aws.dashboard_presigned_url_ttl_seconds == 300


@pytest.fixture
def dashboard_artifacts(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: Any,
    monitoring_metadata: ValidatedBundleMetadata,
) -> DashboardArtifacts:
    completed_at = datetime.now(UTC).replace(microsecond=0)
    window_end = completed_at - timedelta(minutes=10)
    event = monitoring_event_factory(60_001, window_end - timedelta(minutes=30))
    event_root = tmp_path / "events"
    event_root.mkdir()
    (event_root / "events.jsonl").write_bytes(canonical_json_bytes(event) + b"\n")
    policy = MonitoringConfig(minimum_accepted_events=1)
    report_root = tmp_path / "reports"
    run_local_monitoring(
        LocalMonitoringRunSpec(
            bundle_path=monitoring_metadata.path,
            event_directory=event_root,
            report_directory=report_root,
            target_identity=monitoring_target,
            window_end=window_end,
            as_of=completed_at,
        ),
        config=policy,
    )
    return DashboardArtifacts(
        report_root=report_root,
        policy=policy,
        completed_at=completed_at,
        metadata=monitoring_metadata,
    )


def _local_repository(artifacts: DashboardArtifacts) -> LocalDashboardRepository:
    return LocalDashboardRepository(
        report_root=artifacts.report_root,
        model_bundle_path=artifacts.metadata.path,
        max_json_bytes=8 * 1024 * 1024,
        max_html_bytes=16 * 1024 * 1024,
    )


def test_local_repository_reads_latest_history_active_manifest_and_html(
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    repository = _local_repository(dashboard_artifacts)
    latest = repository.read_latest_report()
    status = repository.read_run_status()
    active = repository.read_active_model_manifest()
    history = repository.list_recent_reports(limit=10)

    assert latest is not None and status is not None and active is not None
    assert len(history) == 1
    report = parse_monitoring_report(latest)
    access = repository.html_report_access(
        report_id=report.report_id,
        window_end=report.window.end,
        now=dashboard_artifacts.completed_at,
    )
    assert access is not None and access.content is not None
    assert access.url is None
    assert access.content.startswith(b"<!doctype html>")
    assert report.report_id[:12] in access.filename


def test_local_repository_rejects_symlinked_artifacts(
    tmp_path: Path,
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    unsafe_root = tmp_path / "unsafe-reports"
    unsafe_root.mkdir()
    (unsafe_root / "latest.json").symlink_to(dashboard_artifacts.report_root / "latest.json")
    repository = LocalDashboardRepository(
        report_root=unsafe_root,
        model_bundle_path=dashboard_artifacts.metadata.path,
        max_json_bytes=8 * 1024 * 1024,
        max_html_bytes=16 * 1024 * 1024,
    )

    with pytest.raises(DashboardRepositoryError, match="unsafe_local_artifact"):
        repository.read_latest_report()


def _missing_error(operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "NoSuchKey", "Message": "fake"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        operation,
    )


class FakeDashboardS3:
    def __init__(self, objects: dict[str, bytes], history_keys: list[str]) -> None:
        self.objects = objects
        self.history_keys = history_keys
        self.presign_calls: list[dict[str, Any]] = []
        self.returned_bodies: list[BytesIO] = []

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        key = str(kwargs["Key"])
        if key not in self.objects:
            raise _missing_error("GetObject")
        payload = self.objects[key]
        body = BytesIO(payload)
        self.returned_bodies.append(body)
        return {
            "Body": body,
            "ContentLength": len(payload),
            "LastModified": datetime(2026, 1, 1, tzinfo=UTC),
        }

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]:
        key = str(kwargs["Key"])
        if key not in self.objects:
            raise _missing_error("HeadObject")
        return {"ContentLength": len(self.objects[key])}

    def list_objects_v2(self, **kwargs: Any) -> Mapping[str, Any]:
        del kwargs
        return {
            "Contents": [{"Key": key} for key in reversed(self.history_keys)],
            "IsTruncated": False,
        }

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        self.presign_calls.append({"args": args, "kwargs": kwargs})
        return "https://private-reports.example/report?temporary-signature=fake"


def _s3_repository(
    artifacts: DashboardArtifacts,
) -> tuple[S3DashboardRepository, FakeDashboardS3]:
    report = parse_monitoring_report(
        RawArtifact((artifacts.report_root / "latest.json").read_bytes(), None)
    )
    window_key = report.window.end.strftime("%Y%m%dT%H%M%SZ")
    history_key = f"monitoring/history/{window_key}/{report.report_id}.json"
    html_key = f"monitoring/history/{window_key}/{report.report_id}.html"
    objects = {
        "monitoring/latest.json": (artifacts.report_root / "latest.json").read_bytes(),
        "monitoring/run-status.json": (artifacts.report_root / "run-status.json").read_bytes(),
        history_key: (artifacts.report_root / "latest.json").read_bytes(),
        html_key: (
            artifacts.report_root / "history" / window_key / f"{report.report_id}.html"
        ).read_bytes(),
        "model-bundles/1.0.0/manifest.json": (
            artifacts.metadata.path / "manifest.json"
        ).read_bytes(),
    }
    client = FakeDashboardS3(objects, [history_key])
    repository = S3DashboardRepository(
        client,
        report_bucket="private-report-bucket",
        model_bucket="private-model-bucket",
        active_model_version="1.0.0",
        report_prefix="monitoring/",
        model_prefix="model-bundles/",
        max_json_bytes=8 * 1024 * 1024,
        presigned_url_ttl_seconds=300,
    )
    return repository, client


def test_s3_repository_uses_same_contract_and_short_https_html_link(
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    repository, client = _s3_repository(dashboard_artifacts)
    latest = repository.read_latest_report()
    assert latest is not None
    report = parse_monitoring_report(latest)

    assert repository.read_run_status() is not None
    assert repository.read_active_model_manifest() is not None
    assert len(repository.list_recent_reports(limit=5)) == 1
    assert client.returned_bodies and all(body.closed for body in client.returned_bodies)
    access = repository.html_report_access(
        report_id=report.report_id,
        window_end=report.window.end,
        now=dashboard_artifacts.completed_at,
    )
    assert access is not None
    assert access.content is None
    assert access.url is not None and access.url.startswith("https://")
    assert access.expires_at == dashboard_artifacts.completed_at + timedelta(minutes=5)
    params = client.presign_calls[0]["kwargs"]["Params"]
    assert params["Bucket"] == "private-report-bucket"
    assert params["ResponseContentDisposition"].startswith("attachment;")


def test_snapshot_keeps_active_target_freshness_and_policy_identity_separate(
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    snapshot = load_dashboard_snapshot(
        _local_repository(dashboard_artifacts),
        expected_active_model_version="1.0.0",
        monitoring_policy=dashboard_artifacts.policy,
        captured_at=dashboard_artifacts.completed_at + timedelta(minutes=30),
        history_limit=10,
    )

    assert snapshot.report_availability is ArtifactAvailability.AVAILABLE
    assert snapshot.run_status_availability is ArtifactAvailability.AVAILABLE
    assert snapshot.active_model_availability is ArtifactAvailability.AVAILABLE
    assert snapshot.run_state is RunState.SUCCEEDED
    assert snapshot.report_age_seconds == 1_800
    assert snapshot.policy_matches_report is True
    assert snapshot.active_matches_report_target is True
    assert snapshot.active_model is not None and snapshot.latest_report is not None
    assert snapshot.active_model.manifest_sha256 == (
        snapshot.latest_report.identities.event_carried_target.bundle_manifest_sha256
    )
    assert len(snapshot.recent_reports) == 1


def test_snapshot_marks_exact_stale_boundary_and_never_infers_missing_state(
    tmp_path: Path,
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    stale = load_dashboard_snapshot(
        _local_repository(dashboard_artifacts),
        expected_active_model_version="1.0.0",
        monitoring_policy=dashboard_artifacts.policy,
        captured_at=dashboard_artifacts.completed_at
        + timedelta(seconds=dashboard_artifacts.policy.stale_after_seconds),
        history_limit=10,
    )
    assert stale.run_state is RunState.STALE

    missing_repository = LocalDashboardRepository(
        report_root=tmp_path / "missing-reports",
        model_bundle_path=tmp_path / "missing-model",
        max_json_bytes=1_024,
        max_html_bytes=1_024,
    )
    missing = load_dashboard_snapshot(
        missing_repository,
        expected_active_model_version="1.0.0",
        monitoring_policy=dashboard_artifacts.policy,
        captured_at=dashboard_artifacts.completed_at,
        history_limit=10,
    )
    assert missing.run_state is RunState.NEVER_RUN
    assert missing.latest_report is None
    assert missing.report_availability is ArtifactAvailability.MISSING
    assert missing.active_model_availability is ArtifactAvailability.MISSING


def test_malformed_and_duplicate_key_reports_are_withheld(
    tmp_path: Path,
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_monitoring_report(RawArtifact(b'{"report_id":"a","report_id":"b"}', None))
    deeply_nested = b"[" * 1_200 + b"0" + b"]" * 1_200
    with pytest.raises(ValueError, match="bounded nesting contract"):
        parse_monitoring_report(RawArtifact(deeply_nested, None))

    report_root = tmp_path / "malformed"
    report_root.mkdir()
    (report_root / "latest.json").write_bytes(deeply_nested)
    repository = LocalDashboardRepository(
        report_root=report_root,
        model_bundle_path=dashboard_artifacts.metadata.path,
        max_json_bytes=8 * 1024 * 1024,
        max_html_bytes=16 * 1024 * 1024,
    )
    snapshot = load_dashboard_snapshot(
        repository,
        expected_active_model_version="1.0.0",
        monitoring_policy=dashboard_artifacts.policy,
        captured_at=dashboard_artifacts.completed_at,
        history_limit=10,
    )
    assert snapshot.report_availability is ArtifactAvailability.MALFORMED
    assert snapshot.latest_report is None
    assert snapshot.run_state is None
    assert "latest_report_malformed" in {issue.code for issue in snapshot.issues}


@pytest.mark.parametrize(
    ("path", "replacement", "schema_rejects"),
    (
        (("records", "counts", "raw"), "1000", True),
        (("records", "counts", "raw"), 1000.0, False),
        (("drift", "evaluation", "signals", 0, "required"), "true", True),
    ),
    ids=("numeric-string", "float-to-integer", "boolean-string"),
)
def test_runtime_report_parser_matches_the_exported_strict_schema(
    dashboard_artifacts: DashboardArtifacts,
    repository_root: Path,
    path: tuple[str | int, ...],
    replacement: object,
    schema_rejects: bool,
) -> None:
    artifact = _local_repository(dashboard_artifacts).read_latest_report()
    assert artifact is not None
    payload = json.loads(artifact.payload)
    target: Any = payload
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = replacement
    schema = json.loads(
        (repository_root / "contracts" / "monitoring-report-v1.schema.json").read_bytes()
    )

    assert bool(list(Draft202012Validator(schema).iter_errors(payload))) is schema_rejects
    with pytest.raises(ValueError):
        parse_monitoring_report(RawArtifact(canonical_json_bytes(payload), None))


def test_strict_json_model_loader_preserves_valid_json_datetime_and_uuid_values(
    monitoring_event_factory: Any,
) -> None:
    event = monitoring_event_factory(91, datetime(2026, 1, 1, 0, 30, tzinfo=UTC))

    parsed = validate_strict_json_model(canonical_json_bytes(event), PredictionEventV1)

    assert parsed.event_timestamp == event.event_timestamp
    assert parsed.event_id == event.event_id


def test_current_failed_attempt_remains_separate_when_prior_report_is_missing(
    tmp_path: Path,
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    report_artifact = _local_repository(dashboard_artifacts).read_latest_report()
    assert report_artifact is not None
    prior = parse_monitoring_report(report_artifact)
    report_root = tmp_path / "failed-run"
    report_root.mkdir()
    failed_at = dashboard_artifacts.completed_at + timedelta(minutes=5)
    write_json(
        report_root / "run-status.json",
        RunStatusArtifact(
            latest_attempt_state="failed",
            latest_attempt_at=failed_at,
            latest_success_at=dashboard_artifacts.completed_at,
            latest_report_id=prior.report_id,
            failure_reason="storage_failure",
        ),
    )
    repository = LocalDashboardRepository(
        report_root=report_root,
        model_bundle_path=dashboard_artifacts.metadata.path,
        max_json_bytes=8 * 1024 * 1024,
        max_html_bytes=16 * 1024 * 1024,
    )
    snapshot = load_dashboard_snapshot(
        repository,
        expected_active_model_version="1.0.0",
        monitoring_policy=dashboard_artifacts.policy,
        captured_at=failed_at + timedelta(minutes=1),
        history_limit=10,
    )

    assert snapshot.run_state is RunState.FAILED
    assert snapshot.latest_report is None
    assert "status_report_missing" in {issue.code for issue in snapshot.issues}


def test_policy_identity_mismatch_withholds_thresholds_and_freshness_state(
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    mismatched_policy = dashboard_artifacts.policy.model_copy(update={"minimum_accepted_events": 2})
    snapshot = load_dashboard_snapshot(
        _local_repository(dashboard_artifacts),
        expected_active_model_version="1.0.0",
        monitoring_policy=mismatched_policy,
        captured_at=dashboard_artifacts.completed_at + timedelta(minutes=1),
        history_limit=10,
    )

    assert snapshot.policy_matches_report is False
    assert snapshot.monitoring_policy is None
    assert snapshot.run_state is None
    assert "monitoring_policy_identity_mismatch" in {issue.code for issue in snapshot.issues}


def test_presentation_uses_report_scores_and_exact_policy_thresholds(
    dashboard_artifacts: DashboardArtifacts,
) -> None:
    report_artifact = _local_repository(dashboard_artifacts).read_latest_report()
    assert report_artifact is not None
    report = parse_monitoring_report(report_artifact)
    rows = top_drifting_features(report, dashboard_artifacts.policy)
    assert rows
    assert all(row.warning_threshold is not None for row in rows)
    assert {row.metric for row in rows} <= {"PSI", "Jensen-Shannon distance"}
    numeric = comparable_signals(report, kind="numeric_psi")
    assert numeric
    comparison = distribution_comparison(numeric[0])
    assert list(comparison.columns) == ["Baseline", "Current window"]
    assert prediction_score_trend([report]).shape[0] == 1
    assert list(decision_trend([report]).columns) == ["low_risk", "high_risk"]

    other_target = report.identities.event_carried_target.model_copy(
        update={"model_version": "2.0.0"}
    )
    incomparable = report.model_copy(
        update={
            "identities": report.identities.model_copy(
                update={"event_carried_target": other_target}
            )
        }
    )
    assert comparable_report_history(
        [incomparable, report],
        reference=report,
    ) == (report,)


def test_special_evidence_states_have_distinct_card_classes() -> None:
    states = ("unknown", "stale", "insufficient_data", "pending_labels")
    cards = {state: _state_card("Test", state, "Evidence detail") for state in states}
    for state, markup in cards.items():
        assert f"mg-state {state}" in markup
    assert len(set(cards.values())) == len(states)


def test_streamlit_renders_valid_local_report_without_recomputing_monitoring(
    tmp_path: Path,
    dashboard_artifacts: DashboardArtifacts,
    monkeypatch: pytest.MonkeyPatch,
    repository_root: Path,
) -> None:
    policy_path = tmp_path / "policy.json"
    write_json(policy_path, dashboard_artifacts.policy)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DASHBOARD_REPOSITORY", "local")
    monkeypatch.setenv("LOCAL_REPORT_DIR", str(dashboard_artifacts.report_root))
    monkeypatch.setenv("MODEL_BUNDLE_PATH", str(dashboard_artifacts.metadata.path))
    monkeypatch.setenv("ACTIVE_MODEL_VERSION", "1.0.0")
    monkeypatch.setenv("MONITORING_CONFIG_PATH", str(policy_path))
    app_path = repository_root / "src" / "modelguard" / "dashboard" / "app.py"

    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["ModelGuard AI"]
    assert len(app.dataframe) >= 6
    rendered_markdown = "\n".join(item.value for item in app.markdown)
    assert "mg-state succeeded" in rendered_markdown
    assert "mg-state unknown" in rendered_markdown
