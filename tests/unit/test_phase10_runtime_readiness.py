"""Phase 10 fail-closed runtime hydration and dashboard AWS-health tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import zlib
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from pydantic import ValidationError

import modelguard.storage.versioned_bundle as versioned_bundle_module
from modelguard.core.config import (
    ApiAccessMode,
    AppEnvironment,
    EventSink,
    RuntimeComponent,
    Settings,
)
from modelguard.dashboard.aws_health import (
    AwsDashboardState,
    AwsSourceState,
    DashboardAwsHealthProbe,
)
from modelguard.dashboard.config import DashboardRepositoryMode, DashboardSettings
from modelguard.dashboard.repository import build_dashboard_repository
from modelguard.inference.loader import (
    AwsHydratingModelLoader,
    ModelLoadError,
    ModelLoadFailure,
)
from modelguard.monitoring.aws import PREDICTION_OBJECT_SUFFIXES
from modelguard.monitoring.events import EventIdentity
from modelguard.monitoring.telemetry import MONITOR_COMPLETION_METRIC_NAME
from modelguard.storage.versioned_bundle import (
    BUNDLE_OBJECT_MAX_BYTES,
    MODEL_JOBLIB_COMPRESSED_MAX_BYTES,
    MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES,
    ActiveMonitoringPointer,
    AtomicVersionedBundleInstaller,
    SsmTargetSnapshotResolver,
    VersionedBundleLocation,
    download_versioned_bundle,
    verify_model_joblib_memory_bound,
)
from modelguard.training.bundle import EXPECTED_FILENAMES, ValidatedBundleMetadata


def _client_error(code: str, operation: str = "Read") -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "sanitized fake"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        operation,
    )


def _pointer(
    target: EventIdentity,
    *,
    bucket: str = "modelguard-test-models",
    prefix: str = "model-bundles/1.0.0/",
) -> ActiveMonitoringPointer:
    return ActiveMonitoringPointer(
        target_identity=target,
        bundle=VersionedBundleLocation(
            bucket=bucket,
            key_prefix=prefix,
            object_version_ids={name: f"version-{name}" for name in EXPECTED_FILENAMES},
        ),
    )


class PointerSsm:
    def __init__(
        self,
        pointer: ActiveMonitoringPointer,
        *,
        fail: ClientError | None = None,
        returned_name: str = "/modelguard-ai/demo/models/active",
    ) -> None:
        self.pointer = pointer
        self.fail = fail
        self.returned_name = returned_name
        self.calls: list[dict[str, Any]] = []

    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail
        return {
            "Parameter": {
                "Name": self.returned_name,
                "Type": "String",
                "Value": self.pointer.model_dump_json(),
                "Version": 1,
            }
        }


class BundleObjectS3:
    def __init__(
        self,
        bundle: Path,
        *,
        corrupt_filename: str | None = None,
        fail_filename: str | None = None,
        response_version_override: str | None = None,
        content_length_delta: int = 0,
        location_response: Mapping[str, Any] | BaseException | None = None,
    ) -> None:
        self.bundle = bundle
        self.corrupt_filename = corrupt_filename
        self.fail_filename = fail_filename
        self.response_version_override = response_version_override
        self.content_length_delta = content_length_delta
        self.location_response = (
            {"LocationConstraint": None} if location_response is None else location_response
        )
        self.calls: list[dict[str, Any]] = []
        self.location_calls: list[dict[str, Any]] = []

    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
        self.location_calls.append(kwargs)
        if isinstance(self.location_response, BaseException):
            raise self.location_response
        return self.location_response

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        filename = str(kwargs["Key"]).rsplit("/", 1)[-1]
        if filename == self.fail_filename:
            raise OSError("simulated interrupted transfer")
        payload = (self.bundle / filename).read_bytes()
        if filename == self.corrupt_filename:
            payload = b"{}\n"
        return {
            "Body": BytesIO(payload),
            "ContentLength": len(payload) + self.content_length_delta,
            "VersionId": self.response_version_override or kwargs["VersionId"],
        }


def _aws_api_settings(bundle_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        event_sink=EventSink.DISABLED,
        api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
        alb_allowed_cidr="203.0.113.8/32",
        model_bundle_path=bundle_path,
        active_model_version="1.0.0",
        model_bucket="modelguard-test-models",
        active_model_ssm_parameter="/modelguard-ai/demo/models/active",
    )


def test_api_hydrates_every_exact_version_atomically_before_deserialization(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    pointer = _pointer(monitoring_target)
    ssm = PointerSsm(pointer)
    s3 = BundleObjectS3(monitoring_metadata.path)

    verified = AwsHydratingModelLoader(ssm_client=ssm, s3_client=s3).load(
        _aws_api_settings(destination)
    )

    assert verified.metadata.path == destination
    assert verified.metadata.identity == monitoring_metadata.identity
    assert len(s3.calls) == len(EXPECTED_FILENAMES)
    assert s3.location_calls == [{"Bucket": "modelguard-test-models"}]
    assert {str(call["Key"]).rsplit("/", 1)[-1] for call in s3.calls} == EXPECTED_FILENAMES
    assert all(
        call["VersionId"] == f"version-{str(call['Key']).rsplit('/', 1)[-1]}" for call in s3.calls
    )
    assert ssm.calls == [{"Name": "/modelguard-ai/demo/models/active", "WithDecryption": False}]
    assert all(os.stat(destination / name).st_mode & 0o777 == 0o600 for name in EXPECTED_FILENAMES)
    assert not list(destination.parent.glob(".model-bundle.hydrate-*"))


@pytest.mark.parametrize(
    ("corrupt_filename", "fail_filename", "response_version_override"),
    [
        ("input_schema.json", None, None),
        (None, "metrics.json", None),
        (None, None, "substituted-version"),
    ],
)
def test_api_hydration_corruption_interruption_and_substitution_leave_no_partial_bundle(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
    corrupt_filename: str | None,
    fail_filename: str | None,
    response_version_override: str | None,
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    loader = AwsHydratingModelLoader(
        ssm_client=PointerSsm(_pointer(monitoring_target)),
        s3_client=BundleObjectS3(
            monitoring_metadata.path,
            corrupt_filename=corrupt_filename,
            fail_filename=fail_filename,
            response_version_override=response_version_override,
        ),
    )

    with pytest.raises(ModelLoadError) as error:
        loader.load(_aws_api_settings(destination))

    assert error.value.reason is ModelLoadFailure.HYDRATION_FAILURE
    assert not destination.exists()
    assert not list(destination.parent.glob(".model-bundle.hydrate-*"))


def test_model_joblib_uses_measured_task_safe_compressed_and_inflated_bounds(
    tmp_path: Path,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    model_path = monitoring_metadata.path / "model.joblib"
    assert model_path.stat().st_size < 8 * 1024
    assert MODEL_JOBLIB_COMPRESSED_MAX_BYTES == 64 * 1024
    assert MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES == 4 * 1024 * 1024
    assert verify_model_joblib_memory_bound(model_path) < 64 * 1024

    bomb = tmp_path / "model.joblib"
    bomb.write_bytes(zlib.compress(b"x" * (MODEL_JOBLIB_DECOMPRESSED_MAX_BYTES + 1), level=9))
    assert bomb.stat().st_size < MODEL_JOBLIB_COMPRESSED_MAX_BYTES
    with pytest.raises(ValueError, match="decompression-memory"):
        verify_model_joblib_memory_bound(bomb)


def test_every_bundle_object_has_a_measured_task_safe_download_bound(
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    reviewed_sizes = {
        "baseline_profile.json": 40_618,
        "checksums.sha256": 491,
        "input_schema.json": 2_279,
        "manifest.json": 20_121,
        "metrics.json": 183_619,
        "model.joblib": 4_733,
        "threshold.json": 1_375,
    }
    assert set(BUNDLE_OBJECT_MAX_BYTES) == EXPECTED_FILENAMES
    assert set(reviewed_sizes) == EXPECTED_FILENAMES
    assert all(reviewed_sizes[name] < BUNDLE_OBJECT_MAX_BYTES[name] for name in EXPECTED_FILENAMES)
    assert all(
        (monitoring_metadata.path / name).stat().st_size < BUNDLE_OBJECT_MAX_BYTES[name]
        for name in EXPECTED_FILENAMES
    )
    assert sum(BUNDLE_OBJECT_MAX_BYTES.values()) < 1_250 * 1024


def test_model_joblib_rejects_compressed_boundary_overflow_before_deserialization(
    tmp_path: Path,
) -> None:
    oversized = tmp_path / "model.joblib"
    oversized.write_bytes(b"x" * (MODEL_JOBLIB_COMPRESSED_MAX_BYTES + 1))
    with pytest.raises(ValueError, match="compressed-size"):
        verify_model_joblib_memory_bound(oversized)


def test_api_hydration_rejects_ssm_identity_and_partial_body_before_publication(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    s3 = BundleObjectS3(monitoring_metadata.path)
    wrong_pointer_loader = AwsHydratingModelLoader(
        ssm_client=PointerSsm(
            _pointer(monitoring_target),
            returned_name="/modelguard-ai/demo/models/substituted",
        ),
        s3_client=s3,
    )
    with pytest.raises(ModelLoadError) as wrong_pointer:
        wrong_pointer_loader.load(_aws_api_settings(destination))
    assert wrong_pointer.value.reason is ModelLoadFailure.HYDRATION_FAILURE
    assert s3.calls == []
    assert not destination.exists()

    partial_loader = AwsHydratingModelLoader(
        ssm_client=PointerSsm(_pointer(monitoring_target)),
        s3_client=BundleObjectS3(monitoring_metadata.path, content_length_delta=1),
    )
    with pytest.raises(ModelLoadError) as partial:
        partial_loader.load(_aws_api_settings(destination))
    assert partial.value.reason is ModelLoadFailure.HYDRATION_FAILURE
    assert not destination.exists()


def test_ssm_pointer_rejects_identical_and_conflicting_duplicate_keys_at_every_level(
    monitoring_target: EventIdentity,
) -> None:
    pointer_json = _pointer(monitoring_target).model_dump_json()
    root_marker = '"pointer_schema_version":"modelguard.active-monitor-target.v1",'
    nested_marker = '"bucket":"modelguard-test-models",'
    duplicate_documents = (
        pointer_json.replace(root_marker, root_marker + root_marker, 1),
        pointer_json.replace(
            root_marker,
            root_marker + '"pointer_schema_version":"modelguard.active-monitor-target.v0",',
            1,
        ),
        pointer_json.replace(nested_marker, nested_marker + nested_marker, 1),
        pointer_json.replace(
            nested_marker,
            nested_marker + '"bucket":"substituted-model-bucket",',
            1,
        ),
    )

    class RawPointerSsm:
        def __init__(self, value: str) -> None:
            self.value = value

        def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
            return {
                "Parameter": {
                    "Name": kwargs["Name"],
                    "Type": "String",
                    "Value": self.value,
                    "Version": 1,
                }
            }

    for document in duplicate_documents:
        resolver = SsmTargetSnapshotResolver(
            RawPointerSsm(document),
            parameter_name="/modelguard-ai/demo/models/active",
        )
        with pytest.raises(ValueError, match="duplicate JSON key"):
            resolver.resolve_once()


@pytest.mark.parametrize(
    "location_response",
    [
        {},
        {"LocationConstraint": "eu-west-1"},
        {"LocationConstraint": 42},
        _client_error("AccessDenied", "GetBucketLocation"),
    ],
)
def test_api_hydration_rejects_missing_denied_malformed_or_wrong_bucket_region_before_reads(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
    location_response: Mapping[str, Any] | BaseException,
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    s3 = BundleObjectS3(monitoring_metadata.path, location_response=location_response)

    with pytest.raises(ModelLoadError) as error:
        AwsHydratingModelLoader(
            ssm_client=PointerSsm(_pointer(monitoring_target)),
            s3_client=s3,
        ).load(_aws_api_settings(destination))

    assert error.value.reason is ModelLoadFailure.HYDRATION_FAILURE
    assert s3.calls == []
    assert not destination.exists()


def test_api_refuses_valid_existing_bundle_without_current_version_provenance(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    destination.parent.mkdir(parents=True)
    shutil.copytree(monitoring_metadata.path, destination)
    original_pointer = _pointer(monitoring_target)
    pointer = original_pointer.model_copy(
        update={
            "bundle": original_pointer.bundle.model_copy(
                update={
                    "object_version_ids": {
                        name: f"unavailable-current-{name}" for name in EXPECTED_FILENAMES
                    }
                }
            )
        }
    )
    s3 = BundleObjectS3(monitoring_metadata.path)

    with pytest.raises(ModelLoadError) as error:
        AwsHydratingModelLoader(
            ssm_client=PointerSsm(pointer),
            s3_client=s3,
        ).load(_aws_api_settings(destination))

    assert error.value.reason is ModelLoadFailure.HYDRATION_FAILURE
    assert s3.calls == []
    assert destination.is_dir()


def test_atomic_installer_refuses_scope_changes_and_preserves_existing_destination(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    destination.mkdir(parents=True)
    sentinel = destination / "do-not-overwrite"
    sentinel.write_bytes(b"stable prior bytes")
    installer = AtomicVersionedBundleInstaller(BundleObjectS3(monitoring_metadata.path))

    with pytest.raises(ValueError, match="bucket"):
        installer.install(
            _pointer(monitoring_target, bucket="modelguard-substituted-models"),
            destination=destination,
            expected_bucket="modelguard-test-models",
            expected_model_version="1.0.0",
        )
    assert sentinel.read_bytes() == b"stable prior bytes"
    with pytest.raises(ValueError, match="prefix"):
        installer.install(
            _pointer(monitoring_target, prefix="model-bundles/2.0.0/"),
            destination=destination,
            expected_bucket="modelguard-test-models",
            expected_model_version="1.0.0",
        )
    assert sentinel.read_bytes() == b"stable prior bytes"


def test_bundle_download_interruption_cleans_direct_staging_and_refuses_symlink_destination(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    pointer = _pointer(monitoring_target)

    class InterruptingS3(BundleObjectS3):
        def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
            if str(kwargs["Key"]).endswith("metrics.json"):
                raise KeyboardInterrupt
            return super().get_object(**kwargs)

    staging = tmp_path / "direct-staging"
    with pytest.raises(KeyboardInterrupt):
        download_versioned_bundle(
            InterruptingS3(monitoring_metadata.path),
            pointer,
            staging,
        )
    assert not staging.exists()

    destination = tmp_path / "runtime" / "model-bundle"
    destination.parent.mkdir(parents=True)
    destination.symlink_to(monitoring_metadata.path, target_is_directory=True)
    with pytest.raises(OSError, match="symbolic link"):
        AtomicVersionedBundleInstaller(BundleObjectS3(monitoring_metadata.path)).install(
            pointer,
            destination=destination,
            expected_bucket="modelguard-test-models",
            expected_model_version="1.0.0",
        )
    assert destination.is_symlink()


def test_atomic_installer_rolls_back_when_post_rename_verification_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    destination = tmp_path / "runtime" / "model-bundle"
    original_inspect = versioned_bundle_module.inspect_bundle

    def fail_after_publish(path: Path) -> ValidatedBundleMetadata:
        if path == destination:
            raise ValueError("simulated post-rename verification failure")
        return original_inspect(path)

    monkeypatch.setattr(versioned_bundle_module, "inspect_bundle", fail_after_publish)
    with pytest.raises(ValueError, match="post-rename"):
        AtomicVersionedBundleInstaller(BundleObjectS3(monitoring_metadata.path)).install(
            _pointer(monitoring_target),
            destination=destination,
            expected_bucket="modelguard-test-models",
            expected_model_version="1.0.0",
        )

    assert not destination.exists()
    assert not list(destination.parent.glob(".model-bundle.hydrate-*"))


def _dashboard_settings(**updates: Any) -> DashboardSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.AWS,
        "dashboard_repository": DashboardRepositoryMode.S3,
        "model_bucket": "modelguard-test-models",
        "report_bucket": "modelguard-test-reports",
        "aws_health_required": True,
        "dashboard_source_region": "us-east-1",
        "dashboard_monitor_log_group": "/modelguard-ai/demo/monitor",
        "dashboard_identifier": "modelguard-ai-demo-operations",
        "dashboard_s3_endpoint_url": "https://s3.us-east-1.amazonaws.com",
        "dashboard_cloudwatch_endpoint_url": "https://monitoring.us-east-1.amazonaws.com",
        "dashboard_logs_endpoint_url": "https://logs.us-east-1.amazonaws.com",
    }
    values.update(updates)
    return DashboardSettings(**values)


class HealthS3:
    def __init__(self, responses: dict[str, Mapping[str, Any] | BaseException]) -> None:
        self.responses = responses

    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
        value = self.responses[str(kwargs["Bucket"])]
        if isinstance(value, BaseException):
            raise value
        return value


class HealthCloudWatch:
    def __init__(self, value: Mapping[str, Any] | BaseException) -> None:
        self.value = value
        self.calls: list[dict[str, Any]] = []

    def list_metrics(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


class HealthLogs:
    def __init__(self, value: Mapping[str, Any] | BaseException) -> None:
        self.value = value

    def describe_log_streams(self, **kwargs: Any) -> Mapping[str, Any]:
        assert kwargs == {
            "logGroupName": "/modelguard-ai/demo/monitor",
            "orderBy": "LastEventTime",
            "descending": True,
            "limit": 1,
        }
        if isinstance(self.value, BaseException):
            raise self.value
        return self.value


def _probe(
    *,
    model_location: Mapping[str, Any] | BaseException | None = None,
    report_location: Mapping[str, Any] | BaseException | None = None,
    metrics: Mapping[str, Any] | BaseException | None = None,
    logs: Mapping[str, Any] | BaseException | None = None,
) -> tuple[DashboardAwsHealthProbe, Any]:
    cloudwatch = HealthCloudWatch(
        metrics
        if metrics is not None
        else {
            "Metrics": [
                {
                    "Namespace": "ModelGuardAI",
                    "MetricName": "MonitorCompletions",
                    "Dimensions": [
                        {"Name": "Service", "Value": "monitor"},
                        {"Name": "Environment", "Value": "aws"},
                    ],
                }
            ]
        }
    )
    probe = DashboardAwsHealthProbe(
        _dashboard_settings(),
        s3_client=HealthS3(
            {
                "modelguard-test-models": (
                    model_location if model_location is not None else {"LocationConstraint": None}
                ),
                "modelguard-test-reports": (
                    report_location if report_location is not None else {"LocationConstraint": None}
                ),
            }
        ),
        cloudwatch_client=cloudwatch,
        logs_client=HealthLogs(
            logs
            if logs is not None
            else {
                "logStreams": [
                    {
                        "logStreamName": "ecs/monitor/test",
                        "lastEventTimestamp": 1,
                    }
                ]
            }
        ),
    )
    return probe, cloudwatch


def test_dashboard_aws_health_is_healthy_only_when_every_typed_source_is_healthy() -> None:
    probe, cloudwatch = _probe()

    result = probe.probe()

    assert result.state is AwsDashboardState.HEALTHY
    assert all(source.state is AwsSourceState.HEALTHY for source in result.sources)
    assert cloudwatch.calls == [
        {
            "Namespace": "ModelGuardAI",
            "MetricName": "MonitorCompletions",
            "Dimensions": [
                {"Name": "Service", "Value": "monitor"},
                {"Name": "Environment", "Value": "aws"},
            ],
            "RecentlyActive": "PT3H",
        }
    ]


@pytest.mark.parametrize(
    ("changes", "expected_source", "expected_state"),
    [
        ({"metrics": {"Metrics": []}}, "metrics", AwsSourceState.MISSING_DATA),
        (
            {"metrics": _client_error("AccessDenied")},
            "metrics",
            AwsSourceState.PERMISSION_DENIED,
        ),
        (
            {"model_location": {"LocationConstraint": "eu-west-1"}},
            "model_bucket",
            AwsSourceState.WRONG_REGION,
        ),
        ({"model_location": {}}, "model_bucket", AwsSourceState.MALFORMED_RESPONSE),
        ({"metrics": {"Metrics": "invalid"}}, "metrics", AwsSourceState.MALFORMED_RESPONSE),
        (
            {
                "metrics": {
                    "Metrics": [
                        {
                            "Namespace": "Substituted",
                            "MetricName": "MonitorCompletions",
                            "Dimensions": [],
                        }
                    ]
                }
            },
            "metrics",
            AwsSourceState.MALFORMED_RESPONSE,
        ),
        (
            {"logs": {"logStreams": [{"logStreamName": "missing-timestamp"}]}},
            "monitor_logs",
            AwsSourceState.MALFORMED_RESPONSE,
        ),
        ({"logs": TimeoutError()}, "monitor_logs", AwsSourceState.UNAVAILABLE),
    ],
)
def test_dashboard_aws_health_never_hides_missing_permission_region_or_partial_outage(
    changes: dict[str, Any],
    expected_source: str,
    expected_state: AwsSourceState,
) -> None:
    probe, _ = _probe(**changes)

    result = probe.probe()

    assert result.state is AwsDashboardState.DEGRADED
    affected = next(source for source in result.sources if source.source == expected_source)
    assert affected.state is expected_state


def test_dashboard_total_permission_outage_is_explicitly_unavailable() -> None:
    denied = _client_error("AccessDenied")
    probe, _ = _probe(
        model_location=denied,
        report_location=denied,
        metrics=denied,
        logs=denied,
    )

    result = probe.probe()

    assert result.state is AwsDashboardState.UNAVAILABLE
    assert all(source.state is AwsSourceState.PERMISSION_DENIED for source in result.sources)


def test_dashboard_aws_configuration_rejects_missing_and_cross_region_contracts() -> None:
    with pytest.raises(ValidationError, match="AWS_HEALTH_REQUIRED"):
        _dashboard_settings(aws_health_required=False)
    with pytest.raises(ValidationError, match="exactly match AWS_REGION"):
        _dashboard_settings(dashboard_source_region="eu-west-1")
    with pytest.raises(ValidationError, match="exact demo monitor log group"):
        _dashboard_settings(dashboard_monitor_log_group="/modelguard-ai/demo/api")
    with pytest.raises(ValidationError, match="DASHBOARD_S3_ENDPOINT_URL"):
        _dashboard_settings(dashboard_s3_endpoint_url="https://s3.eu-west-1.amazonaws.com")


def test_dashboard_evidence_client_uses_the_same_exact_validated_s3_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_client(service: str, **kwargs: Any) -> Any:
        calls.append({"service": service, **kwargs})
        return object()

    monkeypatch.setattr("modelguard.dashboard.repository.boto3.client", fake_client)
    build_dashboard_repository(_dashboard_settings())

    assert len(calls) == 1
    assert calls[0]["service"] == "s3"
    assert calls[0]["region_name"] == "us-east-1"
    assert calls[0]["endpoint_url"] == "https://s3.us-east-1.amazonaws.com"


def test_terraform_runtime_contracts_match_monitor_settings_firehose_and_metric(
    repository_root: Path,
) -> None:
    ecs = (repository_root / "infrastructure/environments/demo/ecs.tf").read_text()
    firehose = (repository_root / "infrastructure/environments/demo/firehose.tf").read_text()
    observability = (
        repository_root / "infrastructure/environments/demo/observability.tf"
    ).read_text()
    alarm_sources = (repository_root / "infrastructure/alarm-sources.json").read_text()

    monitor_block = ecs.split("monitor_environment = [", 1)[1].split("resource ", 1)[0]
    rendered_map = monitor_block.split("value = {", 1)[1].split("}[name]", 1)[0]
    expected_names = {
        "APP_ENV",
        "RUNTIME_COMPONENT",
        "HOME",
        "LOG_LEVEL",
        "EVENT_SINK",
        "MODEL_BUNDLE_PATH",
        "ACTIVE_MODEL_VERSION",
        "ACTIVE_MODEL_SSM_PARAMETER",
        "AWS_REGION",
        "MODEL_BUCKET",
        "PREDICTION_BUCKET",
        "REPORT_BUCKET",
        "SNS_TOPIC_ARN",
        "MIN_MONITORING_SAMPLES",
        "MONITORING_CONFIG_PATH",
    }
    substitutions = {
        "local.active_model_version": "1.0.0",
        "aws_ssm_parameter.active_model.name": "/modelguard-ai/demo/models/active",
        "var.aws_region": "us-east-1",
        'module.data_plane.bucket_names["models"]': "model-bucket",
        'module.data_plane.bucket_names["predictions"]': "prediction-bucket",
        'module.data_plane.bucket_names["reports"]': "report-bucket",
        "aws_sns_topic.alerts.arn": (
            "arn:aws:sns:us-east-1:123456789012:modelguard-ai-demo-alerts"
        ),
        "tostring(var.minimum_monitor_records)": "500",
    }
    rendered_environment: dict[str, str] = {}
    for line in rendered_map.splitlines():
        if "=" not in line:
            continue
        name, expression = (part.strip() for part in line.split("=", 1))
        assert name in expected_names
        if expression.startswith('"') and expression.endswith('"'):
            value = expression[1:-1]
        else:
            assert expression in substitutions, f"unresolved monitor expression: {expression}"
            value = substitutions[expression]
        rendered_environment[name] = value
    assert set(rendered_environment) == expected_names
    assert "API_ACCESS_MODE" not in rendered_environment
    assert "ALB_ALLOWED_CIDR" not in rendered_environment

    settings_values = {
        name.casefold(): value
        for name, value in rendered_environment.items()
        if name not in {"HOME", "LOG_LEVEL"}
    }
    settings = Settings(_env_file=None, **settings_values)
    assert settings.runtime_component.value == "monitor"
    assert settings.api_access_mode.value == "local_open"
    with pytest.raises(ValidationError, match="cannot use local_open"):
        Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            runtime_component=RuntimeComponent.API,
        )

    assert 'compression_format = "GZIP"' in firehose
    assert 'file_extension     = ".jsonl.gz"' in firehose
    assert ".jsonl.gz" in PREDICTION_OBJECT_SUFFIXES
    assert MONITOR_COMPLETION_METRIC_NAME == "MonitorCompletions"
    assert f'DASHBOARD_HEALTH_METRIC_NAME          = "{MONITOR_COMPLETION_METRIC_NAME}"' in ecs
    assert f'metric_name         = "{MONITOR_COMPLETION_METRIC_NAME}"' in observability
    assert MONITOR_COMPLETION_METRIC_NAME in alarm_sources


def test_terraform_and_image_verifier_wire_exact_phase10_runtime_contracts(
    repository_root: Path,
) -> None:
    ecs = (repository_root / "infrastructure/environments/demo/ecs.tf").read_text()
    iam = (repository_root / "infrastructure/environments/demo/iam.tf").read_text()
    verifier = (repository_root / "scripts/verify_release_runtime.sh").read_text()

    for variable in (
        "DASHBOARD_SOURCE_REGION",
        "DASHBOARD_S3_ENDPOINT_URL",
        "DASHBOARD_CLOUDWATCH_ENDPOINT_URL",
        "DASHBOARD_LOGS_ENDPOINT_URL",
        "DASHBOARD_MONITOR_LOG_GROUP",
        "MONITORING_CONFIG_PATH",
    ):
        assert variable in ecs
    monitor_policy = iam.split('data "aws_iam_policy_document" "monitor"', 1)[1].split(
        'resource "aws_iam_role_policy" "monitor"', 1
    )[0]
    assert 'sid     = "ReadExactMonitoringBucketRegions"' in monitor_policy
    assert monitor_policy.count('"s3:GetBucketLocation"') == 1
    for bucket in ('["models"]', '["predictions"]', '["reports"]'):
        assert f"module.data_plane.bucket_arns{bucket}" in monitor_policy
    assert "ListVersionedModelBundlePrefix" not in monitor_policy
    api_policy = iam.split('data "aws_iam_policy_document" "api"', 1)[1].split(
        'resource "aws_iam_role_policy" "api"', 1
    )[0]
    assert api_policy.count('"s3:GetBucketLocation"') == 1
    assert 'resources = [module.data_plane.bucket_arns["models"]]' in api_policy
    assert "s3:ListBucket" not in api_policy
    assert "ssm:GetParameters" not in api_policy
    assert "previous_model" not in api_policy
    assert api_policy.count('"ssm:GetParameter"') == 1
    assert "org.opencontainers.image.revision" in verifier
    assert "{{json .Config.Entrypoint}}" in verifier
    assert "{{json .Config.Cmd}}" in verifier
    assert "RUNTIME_VERIFICATION_MODE" in verifier


def _fake_runtime_docker(tmp_path: Path, *, source_revision: str, lock_sha256: str) -> Path:
    executable = tmp_path / "bin" / "docker"
    executable.parent.mkdir(exist_ok=True)
    executable.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" = "image" && "$2" = "inspect" && "$3" = "--format" ]]; then
  format="$4"
  image="$5"
  case "$image" in
    sha256:111*) component=api ;;
    sha256:222*) component=dashboard ;;
    sha256:333*) component=monitor ;;
    *) exit 91 ;;
  esac
  case "$format" in
    '{{.Config.User}}') printf '10001:10001\\n' ;;
    *org.opencontainers.image.revision*) printf '%s\\n' "$FAKE_SOURCE_REVISION" ;;
    *io.modelguard.component*) printf '%s\\n' "$component" ;;
    *io.modelguard.uv-lock.sha256*) printf '%s\\n' "$FAKE_LOCK_SHA256" ;;
    '{{json .Config.Entrypoint}}')
      if [[ "$component" = monitor ]]; then
        printf '["python","-m","modelguard.monitoring.cli"]\\n'
      else
        printf 'null\\n'
      fi
      ;;
    '{{json .Config.Cmd}}')
      if [[ "$component" = api ]]; then
        printf '%s%s\\n' \
          '["python","-m","uvicorn","modelguard.api.main:app","--host","0.0.0.0",' \
          '"--port","8000","--workers","1","--limit-concurrency","64","--timeout-keep-alive","5","--timeout-graceful-shutdown","10","--no-access-log"]'
      elif [[ "$component" = dashboard ]]; then
        printf '%s%s\\n' \
          '["python","-m","streamlit","run","src/modelguard/dashboard/app.py",' \
          '"--server.address","0.0.0.0","--server.port","8501","--server.headless","true","--server.fileWatcherType","none","--browser.gatherUsageStats","false"]'
      else
        printf '["--help"]\\n'
      fi
      ;;
    *) exit 92 ;;
  esac
  exit 0
fi
if [[ "$1" = "run" ]]; then
  [[ "${FAKE_DOCKER_FAIL_RUN:-false}" != true ]]
  exit 0
fi
exit 93
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    assert source_revision.endswith("-dirty") and len(lock_sha256) == 64
    return executable


def _run_fake_runtime_verifier(
    repository_root: Path,
    tmp_path: Path,
    *,
    output: Path,
    fail_run: bool = False,
    lock_label: str | None = None,
) -> subprocess.CompletedProcess[str]:
    source_commit = "a" * 40
    lock_sha = hashlib.sha256((repository_root / "uv.lock").read_bytes()).hexdigest()
    executable = _fake_runtime_docker(
        tmp_path,
        source_revision=f"{source_commit}-dirty",
        lock_sha256=lock_sha,
    )
    env = {
        **os.environ,
        "PATH": f"{executable.parent}:{os.environ['PATH']}",
        "SOURCE_COMMIT": source_commit,
        "RUNTIME_VERIFICATION_MODE": "local_image_id",
        "RUNTIME_VERIFICATION_OUTPUT": str(output),
        "API_IMAGE_REF": f"sha256:{'1' * 64}",
        "DASHBOARD_IMAGE_REF": f"sha256:{'2' * 64}",
        "MONITOR_IMAGE_REF": f"sha256:{'3' * 64}",
        "FAKE_SOURCE_REVISION": f"{source_commit}-dirty",
        "FAKE_LOCK_SHA256": lock_label or lock_sha,
        "FAKE_DOCKER_FAIL_RUN": "true" if fail_run else "false",
    }
    return subprocess.run(
        [str(repository_root / "scripts/verify_release_runtime.sh")],
        cwd=repository_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_runtime_verifier_atomically_seals_mode_0600_lock_bound_evidence(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "sealed" / "runtime-contract.json"
    result = _run_fake_runtime_verifier(repository_root, tmp_path, output=output)

    assert result.returncode == 0, result.stderr
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "modelguard.runtime-contract-verification.v2"
    assert (
        evidence["uv_lock_sha256"]
        == hashlib.sha256((repository_root / "uv.lock").read_bytes()).hexdigest()
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not list(output.parent.glob(".runtime-contract.*"))


def test_failed_runtime_rerun_invalidates_stale_success_and_lock_mismatch(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    failed_output = tmp_path / "failed" / "runtime-contract.json"
    failed_output.parent.mkdir()
    failed_output.write_text('{"status":"passed"}\n', encoding="utf-8")
    failed = _run_fake_runtime_verifier(
        repository_root,
        tmp_path,
        output=failed_output,
        fail_run=True,
    )
    assert failed.returncode != 0
    assert not failed_output.exists()

    mismatch_output = tmp_path / "mismatch" / "runtime-contract.json"
    mismatch_output.parent.mkdir()
    mismatch_output.write_text('{"status":"passed"}\n', encoding="utf-8")
    mismatch = _run_fake_runtime_verifier(
        repository_root,
        tmp_path,
        output=mismatch_output,
        lock_label="0" * 64,
    )
    assert mismatch.returncode != 0
    assert not mismatch_output.exists()
