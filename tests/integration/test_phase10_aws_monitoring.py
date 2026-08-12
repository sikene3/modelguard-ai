"""One-shot AWS monitor integration tests with injected, in-memory service doubles."""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from pytest import CaptureFixture, MonkeyPatch

import modelguard.monitoring.aws_run as monitoring_aws_run
import modelguard.monitoring.cli as monitoring_cli
from modelguard.core.config import AppEnvironment, EventSink, RuntimeComponent, Settings
from modelguard.core.serialization import canonical_json_bytes
from modelguard.monitoring.aws import S3RunStateStore
from modelguard.monitoring.aws_run import (
    AwsRunClients,
    AwsRunExecution,
    AwsRunExitCode,
    AwsRunOutput,
    _require_bucket_region,
    execute_aws_monitoring_once,
)
from modelguard.monitoring.config import (
    AWS_LOCKED_MONITORING_POLICY_SHA256,
    MonitoringConfig,
)
from modelguard.monitoring.events import EventIdentity
from modelguard.monitoring.persistence import RunStatusArtifact
from modelguard.storage.versioned_bundle import ActiveMonitoringPointer, VersionedBundleLocation
from modelguard.training.bundle import EXPECTED_FILENAMES, ValidatedBundleMetadata


def _error(code: str, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "sanitized fake"},
            "ResponseMetadata": {"HTTPStatusCode": 403 if code == "AccessDenied" else 404},
        },
        operation,
    )


def _pointer(target: EventIdentity) -> ActiveMonitoringPointer:
    return ActiveMonitoringPointer(
        target_identity=target,
        bundle=VersionedBundleLocation(
            bucket="modelguard-test-models",
            key_prefix="model-bundles/1.0.0/",
            object_version_ids={name: f"version-{name}" for name in EXPECTED_FILENAMES},
        ),
    )


class FakeSsm:
    def __init__(self, pointer: ActiveMonitoringPointer, *, denied: bool = False) -> None:
        self.pointer = pointer
        self.denied = denied

    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
        del kwargs
        if self.denied:
            raise _error("AccessDenied", "GetParameter")
        return {
            "Parameter": {
                "Name": "/modelguard-ai/demo/models/active",
                "Type": "String",
                "Value": self.pointer.model_dump_json(),
                "Version": 1,
            }
        }


class IntegratedS3:
    def __init__(
        self,
        bundle: Path,
        event_payload: bytes | None,
        *,
        corrupt_bundle: bool = False,
        fail_report_write: bool = False,
        fail_run_status: bool = False,
        prediction_version_override: str | None = None,
        truncate_prediction: bool = False,
        corrupt_prediction_gzip: bool = False,
        bucket_region: str | None = None,
        deny_bucket_location: bool = False,
    ) -> None:
        self.bundle = bundle
        self.event_payload = event_payload
        self.stored_event_payload = (
            b"\x1f\x8b\x08\x00" + b"x" * 30
            if corrupt_prediction_gzip
            else gzip.compress(event_payload, mtime=0)
            if event_payload is not None
            else None
        )
        self.corrupt_bundle = corrupt_bundle
        self.fail_report_write = fail_report_write
        self.fail_run_status = fail_run_status
        self.prediction_version_override = prediction_version_override
        self.truncate_prediction = truncate_prediction
        self.bucket_region = bucket_region
        self.deny_bucket_location = deny_bucket_location
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.counter = 0

    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
        del kwargs
        if self.deny_bucket_location:
            raise _error("AccessDenied", "GetBucketLocation")
        return {"LocationConstraint": self.bucket_region}

    def list_objects_v2(self, **kwargs: Any) -> Mapping[str, Any]:
        if kwargs["Bucket"] == "modelguard-test-predictions":
            event_key = "predictions/year=2026/month=01/day=01/hour=00/events.jsonl.gz"
            contents = (
                [{"Key": event_key}]
                if self.event_payload is not None and event_key.startswith(str(kwargs["Prefix"]))
                else []
            )
            return {"Contents": contents, "IsTruncated": False}
        return {"Contents": [], "IsTruncated": False}

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]:
        assert self.stored_event_payload is not None
        return {
            "ContentLength": len(self.stored_event_payload),
            "ETag": '"prediction-etag"',
            "VersionId": "prediction-version",
        }

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        if bucket == "modelguard-test-models":
            filename = key.rsplit("/", 1)[-1]
            payload = (self.bundle / filename).read_bytes()
            if self.corrupt_bundle and filename == "manifest.json":
                payload = b"{}\n"
            return {
                "Body": BytesIO(payload),
                "ContentLength": len(payload),
                "VersionId": kwargs["VersionId"],
            }
        if bucket == "modelguard-test-predictions":
            assert self.stored_event_payload is not None
            payload = (
                self.stored_event_payload[:-1]
                if self.truncate_prediction
                else self.stored_event_payload
            )
            return {
                "Body": BytesIO(payload),
                "ETag": '"prediction-etag"',
                "VersionId": self.prediction_version_override or "prediction-version",
            }
        if key not in self.objects:
            raise _error("NoSuchKey", "GetObject")
        payload, etag = self.objects[key]
        return {"Body": BytesIO(payload), "ETag": etag}

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        key = str(kwargs["Key"])
        if self.fail_report_write and "/history/" in key:
            raise OSError("simulated report sink outage")
        if self.fail_run_status and key.endswith("run-status.json"):
            raise OSError("simulated run-status sink outage")
        current = self.objects.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise _error("PreconditionFailed", "PutObject")
        if "IfMatch" in kwargs and (current is None or current[1] != kwargs["IfMatch"]):
            raise _error("PreconditionFailed", "PutObject")
        self.counter += 1
        etag = f'"etag-{self.counter}"'
        payload = kwargs["Body"]
        assert isinstance(payload, bytes)
        self.objects[key] = (payload, etag)
        return {"ETag": etag}


class FakeSns:
    def __init__(self, *, denied: bool = False) -> None:
        self.denied = denied
        self.calls: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        if self.denied:
            raise _error("AccessDenied", "Publish")
        return {"MessageId": "message-1"}


def _settings(tmp_path: Path, **updates: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.AWS,
        "runtime_component": RuntimeComponent.MONITOR,
        "event_sink": EventSink.DISABLED,
        "model_bundle_path": tmp_path / "runtime" / "model-bundle",
        "active_model_version": "1.0.0",
        "aws_region": "us-east-1",
        "model_bucket": "modelguard-test-models",
        "prediction_bucket": "modelguard-test-predictions",
        "report_bucket": "modelguard-test-reports",
        "active_model_ssm_parameter": "/modelguard-ai/demo/models/active",
        "sns_topic_arn": ("arn:aws:sns:us-east-1:123456789012:modelguard-ai-demo-alerts"),
        "monitoring_config_path": Path("/app/configs/phase-05-monitoring.json"),
        "min_monitoring_samples": 500,
    }
    values.update(updates)
    return Settings(**values)


def _execute(
    *,
    tmp_path: Path,
    target: EventIdentity,
    metadata: ValidatedBundleMetadata,
    event_payload: bytes | None,
    denied_ssm: bool = False,
    denied_sns: bool = False,
    corrupt_bundle: bool = False,
    fail_report_write: bool = False,
    fail_run_status: bool = False,
    prediction_version_override: str | None = None,
    truncate_prediction: bool = False,
    bucket_region: str | None = None,
    deny_bucket_location: bool = False,
    settings_updates: dict[str, Any] | None = None,
) -> tuple[AwsRunExecution, IntegratedS3, list[str]]:
    s3 = IntegratedS3(
        metadata.path,
        event_payload,
        corrupt_bundle=corrupt_bundle,
        fail_report_write=fail_report_write,
        fail_run_status=fail_run_status,
        prediction_version_override=prediction_version_override,
        truncate_prediction=truncate_prediction,
        bucket_region=bucket_region,
        deny_bucket_location=deny_bucket_location,
    )
    emf: list[str] = []
    result = execute_aws_monitoring_once(
        _settings(tmp_path, **(settings_updates or {})),
        config=MonitoringConfig(),
        as_of=datetime(2026, 1, 1, 1, 10, tzinfo=UTC),
        window_end=datetime(2026, 1, 1, 1, tzinfo=UTC),
        clients=AwsRunClients(
            ssm=FakeSsm(_pointer(target), denied=denied_ssm),
            s3=s3,
            sns=FakeSns(denied=denied_sns),
        ),
        emf_writer=emf.append,
    )
    return result, s3, emf


def test_aws_run_executes_one_cycle_publishes_evidence_and_is_idempotent(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    payload = b"".join(
        canonical_json_bytes(
            monitoring_event_factory(index, datetime(2026, 1, 1, 0, 30, tzinfo=UTC))
        )
        + b"\n"
        for index in range(500)
    )
    first, s3, emf = _execute(
        tmp_path=tmp_path,
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=payload,
    )

    assert first.exit_code is AwsRunExitCode.SUCCEEDED
    assert first.output.status == "succeeded"
    assert first.output.accepted_target == 500
    assert first.output.monitoring_policy_sha256 == AWS_LOCKED_MONITORING_POLICY_SHA256
    assert first.output.performance_state == "unknown"
    assert first.output.latest_updated is True
    assert len(emf) == 1
    first_history = {key: value[0] for key, value in s3.objects.items() if "/history/" in key}

    second = execute_aws_monitoring_once(
        _settings(tmp_path / "second-cycle"),
        config=MonitoringConfig(),
        as_of=datetime(2026, 1, 1, 1, 10, tzinfo=UTC),
        window_end=datetime(2026, 1, 1, 1, tzinfo=UTC),
        clients=AwsRunClients(
            ssm=FakeSsm(_pointer(monitoring_target)),
            s3=s3,
            sns=FakeSns(),
        ),
        emf_writer=lambda _: None,
    )
    assert second.exit_code is AwsRunExitCode.SUCCEEDED
    assert second.output.report_id == first.output.report_id
    assert second.output.json_sha256 == first.output.json_sha256
    assert second.output.latest_updated is False
    assert {
        key: value[0] for key, value in s3.objects.items() if "/history/" in key
    } == first_history


def test_aws_run_fails_closed_on_incomplete_corrupt_permission_sink_and_region_cases(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    incomplete, _, _ = _execute(
        tmp_path=tmp_path / "incomplete",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=None,
    )
    assert incomplete.exit_code is AwsRunExitCode.INVALID_OR_INCOMPLETE_EVIDENCE
    assert incomplete.output.category == "incomplete_monitoring_evidence"

    corrupt, _, _ = _execute(
        tmp_path=tmp_path / "corrupt",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=None,
        corrupt_bundle=True,
    )
    assert corrupt.exit_code is AwsRunExitCode.INVALID_OR_INCOMPLETE_EVIDENCE
    assert corrupt.output.category == "invalid_monitoring_evidence"

    denied, _, _ = _execute(
        tmp_path=tmp_path / "denied",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=None,
        denied_ssm=True,
    )
    assert denied.exit_code is AwsRunExitCode.AWS_ACCESS_FAILURE
    assert denied.output.category == "aws_permission_denied"

    sink, _, _ = _execute(
        tmp_path=tmp_path / "sink",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=None,
        fail_report_write=True,
    )
    assert sink.exit_code is AwsRunExitCode.PERSISTENCE_FAILURE
    assert sink.output.category == "persistence_failure"

    wrong_region, _, _ = _execute(
        tmp_path=tmp_path / "region",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=None,
        settings_updates={"aws_region": "eu-west-1"},
    )
    assert wrong_region.exit_code is AwsRunExitCode.INVALID_CONFIGURATION
    assert wrong_region.output.category == "invalid_aws_run_configuration"


def test_aws_run_normalizes_invalid_deflate_to_one_result_and_persists_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    s3 = IntegratedS3(
        monitoring_metadata.path,
        b"placeholder",
        corrupt_prediction_gzip=True,
    )
    clients = AwsRunClients(
        ssm=FakeSsm(_pointer(monitoring_target)),
        s3=s3,
        sns=FakeSns(),
    )
    monkeypatch.setattr(monitoring_cli, "load_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        monitoring_cli,
        "load_monitoring_config",
        lambda _: MonitoringConfig(),
    )
    monkeypatch.setattr(monitoring_aws_run, "_aws_clients", lambda _: clients)

    assert monitoring_cli.main(
        [
            "aws-run",
            "--as-of",
            "2026-01-01T01:10:00Z",
            "--window-end",
            "2026-01-01T01:00:00Z",
        ]
    ) == int(AwsRunExitCode.INVALID_OR_INCOMPLETE_EVIDENCE)
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.count("\n") == 1
    payload = json.loads(output.out)
    assert payload["as_of"] == "2026-01-01T01:10:00Z"
    assert payload["category"] == "invalid_monitoring_evidence"
    assert payload["monitoring_policy_sha256"] == AWS_LOCKED_MONITORING_POLICY_SHA256
    assert payload["output_schema_version"] == "modelguard.monitor-aws-run-output.v1"
    assert payload["status"] == "failed"
    assert all(
        payload[field] is None
        for field in (
            "accepted_target",
            "data_quality_state",
            "drift_state",
            "html_key",
            "html_sha256",
            "json_key",
            "json_sha256",
            "latest_updated",
            "performance_state",
            "report_id",
        )
    )
    status = RunStatusArtifact.model_validate_json(
        s3.objects["monitoring/run-status.json"][0], strict=True
    )
    assert status.latest_attempt_state == "failed"
    assert status.failure_reason == "invalid_monitoring_evidence"


def test_aws_run_rejects_stale_partial_cross_region_and_unwritable_status_evidence(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    event = monitoring_event_factory(1, datetime(2026, 1, 1, 0, 30, tzinfo=UTC))
    payload = canonical_json_bytes(event) + b"\n"

    stale, _, _ = _execute(
        tmp_path=tmp_path / "stale",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=payload,
        prediction_version_override="stale-version",
    )
    assert stale.exit_code is AwsRunExitCode.INVALID_OR_INCOMPLETE_EVIDENCE
    assert stale.output.category == "invalid_monitoring_evidence"

    partial, _, _ = _execute(
        tmp_path=tmp_path / "partial",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=payload,
        truncate_prediction=True,
    )
    assert partial.exit_code is AwsRunExitCode.INVALID_OR_INCOMPLETE_EVIDENCE
    assert partial.output.category == "invalid_monitoring_evidence"

    cross_region, _, _ = _execute(
        tmp_path=tmp_path / "cross-region",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=payload,
        bucket_region="eu-west-1",
    )
    assert cross_region.exit_code is AwsRunExitCode.INVALID_CONFIGURATION
    assert cross_region.output.category == "invalid_aws_run_configuration"

    location_denied, _, _ = _execute(
        tmp_path=tmp_path / "location-denied",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=payload,
        deny_bucket_location=True,
    )
    assert location_denied.exit_code is AwsRunExitCode.AWS_ACCESS_FAILURE
    assert location_denied.output.category == "aws_permission_denied"

    status_sink, _, _ = _execute(
        tmp_path=tmp_path / "status-sink",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=payload,
        fail_run_status=True,
    )
    assert status_sink.exit_code is AwsRunExitCode.PERSISTENCE_FAILURE
    assert status_sink.output.category == "run_status_persistence_failure"


def test_aws_run_alert_and_telemetry_failures_remain_nonzero(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    alert, _, _ = _execute(
        tmp_path=tmp_path / "alert",
        target=monitoring_target,
        metadata=monitoring_metadata,
        event_payload=b"not-json\n",
        denied_sns=True,
    )
    assert alert.exit_code is AwsRunExitCode.PERSISTENCE_FAILURE
    assert alert.output.category == "alert_sink_failure"

    s3 = IntegratedS3(monitoring_metadata.path, None)

    def fail_telemetry(_: str) -> None:
        raise OSError("simulated telemetry sink outage")

    telemetry = execute_aws_monitoring_once(
        _settings(tmp_path / "telemetry"),
        config=MonitoringConfig(),
        as_of=datetime(2026, 1, 1, 1, 10, tzinfo=UTC),
        window_end=datetime(2026, 1, 1, 1, tzinfo=UTC),
        clients=AwsRunClients(
            ssm=FakeSsm(_pointer(monitoring_target)),
            s3=s3,
            sns=FakeSns(),
        ),
        emf_writer=fail_telemetry,
    )
    assert telemetry.exit_code is AwsRunExitCode.PERSISTENCE_FAILURE
    assert telemetry.output.category == "persistence_failure"


def test_s3_run_status_preserves_last_success_when_a_later_attempt_fails(
    tmp_path: Path,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    s3 = IntegratedS3(monitoring_metadata.path, None)
    store = S3RunStateStore(s3, bucket="modelguard-test-reports")
    success_at = datetime(2026, 1, 1, 1, 10, tzinfo=UTC)
    failure_at = datetime(2026, 1, 1, 2, 10, tzinfo=UTC)

    assert store.record_success(completed_at=success_at, report_id="a" * 64)
    assert store.record_failure(attempted_at=failure_at, reason="permission_failure")

    payload = s3.objects["monitoring/run-status.json"][0]
    persisted = RunStatusArtifact.model_validate_json(payload)
    assert persisted.latest_attempt_state == "failed"
    assert persisted.latest_attempt_at == failure_at
    assert persisted.latest_success_at == success_at
    assert persisted.latest_report_id == "a" * 64


def test_aws_run_cli_prints_one_machine_readable_result_and_propagates_status(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(monitoring_cli, "load_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(
        monitoring_cli,
        "load_monitoring_config",
        lambda _: MonitoringConfig(),
    )
    execution = AwsRunExecution(
        exit_code=AwsRunExitCode.AWS_ACCESS_FAILURE,
        output=AwsRunOutput(
            status="failed",
            category="aws_permission_denied",
            as_of="2026-01-01T01:10:00Z",
        ),
    )
    monkeypatch.setattr(
        monitoring_cli,
        "execute_aws_monitoring_once",
        lambda *args, **kwargs: execution,
    )

    assert monitoring_cli.main(["aws-run", "--as-of", "2026-01-01T01:10:00Z"]) == 3
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == execution.output.model_dump(mode="json")
    assert output.out.count("\n") == 1


def test_aws_run_cli_rejects_invalid_time_with_bounded_machine_output(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(monitoring_cli, "load_settings", lambda: Settings(_env_file=None))

    assert monitoring_cli.main(["aws-run", "--as-of", "not-a-time"]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "as_of": "1970-01-01T00:00:00Z",
        "category": "invalid_aws_run_configuration",
        "output_schema_version": "modelguard.monitor-aws-run-output.v1",
        "status": "failed",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("smoothing_epsilon", 2e-6),
        ("psi_warning_threshold", 0.11),
        ("minimum_accepted_events", 499),
        ("performance_warning_delta", 0.11),
        ("window_seconds", 7_200),
    ),
)
def test_aws_run_rejects_every_semantic_policy_mutation_before_aws_access(
    field: str,
    value: float | int,
    tmp_path: Path,
    monitoring_target: EventIdentity,
) -> None:
    class NoAws:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"AWS access occurred through {name}")

    mutated = MonitoringConfig.model_validate(
        {**MonitoringConfig().model_dump(mode="python"), field: value}
    )
    result = execute_aws_monitoring_once(
        _settings(tmp_path),
        config=mutated,
        as_of=datetime(2026, 1, 1, 1, 10, tzinfo=UTC),
        clients=AwsRunClients(ssm=NoAws(), s3=NoAws(), sns=NoAws()),  # type: ignore[arg-type]
    )
    assert result.exit_code is AwsRunExitCode.INVALID_CONFIGURATION
    assert result.output.category == "invalid_aws_run_configuration"
    assert result.output.monitoring_policy_sha256 == AWS_LOCKED_MONITORING_POLICY_SHA256


def test_aws_run_cli_has_no_policy_override_surface(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    substituted = tmp_path / "substituted-policy.json"
    substituted.write_text(json.dumps({"mutation": "all-semantics"}), encoding="utf-8")
    called = False

    def unexpected(*args: Any, **kwargs: Any) -> AwsRunExecution:
        nonlocal called
        called = True
        raise AssertionError("aws-run must reject substituted policy before execution")

    monkeypatch.setattr(monitoring_cli, "execute_aws_monitoring_once", unexpected)
    with pytest.raises(SystemExit) as error:
        monitoring_cli.main(["aws-run", "--config", str(substituted)])
    assert error.value.code == 2
    assert not called


@pytest.mark.parametrize(
    "response",
    ({}, {"LocationConstraint": 42}, {"LocationConstraint": "eu-west-1"}),
)
def test_monitor_bucket_region_rejects_missing_malformed_and_wrong_values(
    response: Mapping[str, Any],
) -> None:
    class LocationS3:
        def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
            assert kwargs == {"Bucket": "exact-bucket"}
            return response

    with pytest.raises(ValueError, match=r"malformed|cross-Region"):
        _require_bucket_region(LocationS3(), bucket="exact-bucket", region="us-east-1")  # type: ignore[arg-type]
