"""Exactly-one-cycle AWS monitoring orchestration with deterministic bounded output."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Literal, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field

from modelguard.core.config import AppEnvironment, RuntimeComponent, Settings
from modelguard.core.serialization import StrictArtifactModel
from modelguard.monitoring.aws import (
    S3Client,
    S3PublishedReport,
    S3ReportStore,
    S3RunStateStore,
    SnsAlertSink,
    SnsClient,
    freeze_s3_raw_snapshot,
)
from modelguard.monitoring.config import (
    AWS_LOCKED_MONITORING_POLICY_SHA256,
    MonitoringConfig,
    monitoring_config_hash,
)
from modelguard.monitoring.events import parse_utc_timestamp, resolve_window
from modelguard.monitoring.service import evaluate_monitoring_snapshots
from modelguard.monitoring.state import DataQualityState, ensure_utc
from modelguard.monitoring.telemetry import EmfWriter, emit_monitor_completion_emf
from modelguard.storage.versioned_bundle import (
    AtomicVersionedBundleInstaller,
    SsmPointerClient,
    SsmTargetSnapshotResolver,
)


class AwsRunExitCode(IntEnum):
    SUCCEEDED = 0
    INVALID_CONFIGURATION = 2
    AWS_ACCESS_FAILURE = 3
    INVALID_OR_INCOMPLETE_EVIDENCE = 4
    PERSISTENCE_FAILURE = 5


class AwsRunOutput(StrictArtifactModel):
    output_schema_version: Literal["modelguard.monitor-aws-run-output.v1"] = (
        "modelguard.monitor-aws-run-output.v1"
    )
    status: Literal["succeeded", "failed"]
    category: str = Field(pattern=r"^[a-z0-9_]+$")
    as_of: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
    report_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    accepted_target: int | None = Field(default=None, ge=0)
    data_quality_state: str | None = None
    drift_state: str | None = None
    performance_state: str | None = None
    json_key: str | None = None
    json_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    html_key: str | None = None
    html_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latest_updated: bool | None = None
    monitoring_policy_sha256: str = Field(
        default=AWS_LOCKED_MONITORING_POLICY_SHA256,
        pattern=r"^[0-9a-f]{64}$",
    )


@dataclass(frozen=True)
class AwsRunExecution:
    exit_code: AwsRunExitCode
    output: AwsRunOutput


@dataclass(frozen=True)
class AwsRunClients:
    ssm: SsmPointerClient
    s3: S3Client
    sns: SnsClient


def _aws_clients(settings: Settings) -> AwsRunClients:
    config = Config(
        connect_timeout=1.0,
        read_timeout=5.0,
        retries={"max_attempts": 3, "mode": "standard"},
        user_agent_extra="modelguard-monitor-aws-run/1",
    )
    # No profile or credentials are passed; ECS resolves its task role via the SDK provider chain.
    return AwsRunClients(
        ssm=cast(
            SsmPointerClient,
            boto3.client("ssm", region_name=settings.aws_region, config=config),
        ),
        s3=cast(S3Client, boto3.client("s3", region_name=settings.aws_region, config=config)),
        sns=cast(SnsClient, boto3.client("sns", region_name=settings.aws_region, config=config)),
    )


def _validate_settings(settings: Settings, config: MonitoringConfig) -> None:
    if settings.app_env is not AppEnvironment.AWS:
        raise ValueError("aws-run requires APP_ENV=aws")
    if settings.runtime_component is not RuntimeComponent.MONITOR:
        raise ValueError("aws-run requires RUNTIME_COMPONENT=monitor")
    if settings.aws_region != "us-east-1":
        raise ValueError("aws-run is pinned to the canonical us-east-1 project Region")
    required = {
        "MODEL_BUCKET": settings.model_bucket,
        "PREDICTION_BUCKET": settings.prediction_bucket,
        "REPORT_BUCKET": settings.report_bucket,
        "ACTIVE_MODEL_SSM_PARAMETER": settings.active_model_ssm_parameter,
        "SNS_TOPIC_ARN": settings.sns_topic_arn,
    }
    if any(not value for value in required.values()):
        raise ValueError("aws-run required configuration is incomplete")
    buckets = {settings.model_bucket, settings.prediction_bucket, settings.report_bucket}
    if len(buckets) != 3:
        raise ValueError("aws-run model, prediction, and report buckets must be distinct")
    if not settings.model_bundle_path.is_absolute():
        raise ValueError("aws-run bundle installation path must be absolute")
    if settings.monitoring_config_path != Path("/app/configs/phase-05-monitoring.json"):
        raise ValueError("aws-run must use the locked image monitoring configuration")
    policy_sha256 = monitoring_config_hash(config).digest
    if policy_sha256 != AWS_LOCKED_MONITORING_POLICY_SHA256:
        raise ValueError("aws-run monitoring policy does not match the embedded contract")
    if config.minimum_accepted_events != settings.min_monitoring_samples:
        raise ValueError("aws-run monitoring sample thresholds are contradictory")
    if settings.active_model_ssm_parameter != "/modelguard-ai/demo/models/active":
        raise ValueError("aws-run active pointer must use the exact demo parameter")
    topic_pattern = re.compile(
        rf"^arn:aws:sns:{re.escape(settings.aws_region)}:[0-9]{{12}}:"
        r"modelguard-ai-demo-alerts$"
    )
    if topic_pattern.fullmatch(str(settings.sns_topic_arn)) is None:
        raise ValueError("aws-run alert topic is malformed or cross-Region")


def _require_bucket_region(client: S3Client, *, bucket: str, region: str) -> None:
    response = client.get_bucket_location(Bucket=bucket)
    if "LocationConstraint" not in response:
        raise ValueError("aws-run S3 bucket location response is malformed")
    location = response["LocationConstraint"]
    actual_region = (
        "us-east-1" if location is None else "eu-west-1" if location == "EU" else location
    )
    if not isinstance(actual_region, str) or actual_region != region:
        raise ValueError("aws-run S3 bucket is malformed or cross-Region")


def _canonical_z(value: datetime) -> str:
    return ensure_utc(value, name="as_of").isoformat(timespec="seconds").replace("+00:00", "Z")


def _stderr_emf_writer(line: str) -> None:
    sys.stderr.write(f"{line}\n")
    sys.stderr.flush()


def _client_error_is_access_denied(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in {
        "AccessDenied",
        "AccessDeniedException",
        "AuthorizationError",
        "UnauthorizedOperation",
    }


def _failure(
    *,
    as_of: datetime,
    category: str,
    exit_code: AwsRunExitCode,
    published: S3PublishedReport | None = None,
    report_fields: dict[str, Any] | None = None,
) -> AwsRunExecution:
    fields = report_fields or {}
    if published is not None:
        fields.update(
            {
                "json_key": published.json_key,
                "json_sha256": published.json_sha256,
                "html_key": published.html_key,
                "html_sha256": published.html_sha256,
                "latest_updated": published.latest_updated,
            }
        )
    return AwsRunExecution(
        exit_code=exit_code,
        output=AwsRunOutput(
            status="failed",
            category=category,
            as_of=_canonical_z(as_of),
            **fields,
        ),
    )


def execute_aws_monitoring_once(
    settings: Settings,
    *,
    config: MonitoringConfig,
    as_of: datetime,
    window_end: datetime | None = None,
    clients: AwsRunClients | None = None,
    emf_writer: EmfWriter | None = None,
) -> AwsRunExecution:
    """Execute one bounded cycle; never loop, daemonize, fit, or mutate the target model."""

    normalized_as_of = ensure_utc(as_of, name="as_of")
    stage = "configuration"
    status_store: S3RunStateStore | None = None
    published: S3PublishedReport | None = None
    report_fields: dict[str, Any] | None = None
    try:
        _validate_settings(settings, config)
        resolved_clients = clients or _aws_clients(settings)
        if (
            settings.report_bucket is None
            or settings.model_bucket is None
            or settings.prediction_bucket is None
            or settings.active_model_ssm_parameter is None
            or settings.sns_topic_arn is None
        ):
            raise ValueError("aws-run required configuration is incomplete")
        for bucket in (
            settings.model_bucket,
            settings.prediction_bucket,
            settings.report_bucket,
        ):
            _require_bucket_region(
                resolved_clients.s3,
                bucket=bucket,
                region=settings.aws_region,
            )
        status_store = S3RunStateStore(resolved_clients.s3, bucket=settings.report_bucket)

        stage = "target_evidence"
        pointer = SsmTargetSnapshotResolver(
            resolved_clients.ssm,
            parameter_name=settings.active_model_ssm_parameter,
        ).resolve_once()
        installed = AtomicVersionedBundleInstaller(resolved_clients.s3).install(
            pointer,
            destination=settings.model_bundle_path,
            expected_bucket=settings.model_bucket,
            expected_model_version=settings.active_model_version,
        )
        window = resolve_window(as_of=normalized_as_of, config=config, window_end=window_end)

        stage = "prediction_evidence"
        event_snapshot = freeze_s3_raw_snapshot(
            resolved_clients.s3,
            bucket=settings.prediction_bucket,
            prefix="predictions/",
        )
        evaluation = evaluate_monitoring_snapshots(
            metadata=installed.metadata,
            target_identity=pointer.target_identity,
            known_non_target_metadata=(),
            event_snapshot=event_snapshot,
            label_snapshot=None,
            window=window,
            config=config,
        )
        report = evaluation.report
        counts = report.records.counts
        report_fields = {
            "report_id": report.report_id,
            "accepted_target": counts.accepted_target,
            "data_quality_state": report.states.data_quality.value,
            "drift_state": report.states.drift.value,
            "performance_state": report.states.performance.value,
        }

        stage = "report_persistence"
        published = S3ReportStore(
            resolved_clients.s3,
            bucket=settings.report_bucket,
        ).publish(
            report,
            alert_sink=SnsAlertSink(resolved_clients.sns, topic_arn=settings.sns_topic_arn),
        )
        if published.alert_failure_count:
            status_store.record_failure(
                attempted_at=normalized_as_of,
                reason="alert_sink_failure",
            )
            return _failure(
                as_of=normalized_as_of,
                category="alert_sink_failure",
                exit_code=AwsRunExitCode.PERSISTENCE_FAILURE,
                published=published,
                report_fields=report_fields,
            )

        stage = "telemetry"
        emit_monitor_completion_emf(
            report,
            as_of=normalized_as_of,
            environment=AppEnvironment.AWS,
            writer=emf_writer or _stderr_emf_writer,
        )
        if report.states.data_quality in {
            DataQualityState.INVALID,
            DataQualityState.INSUFFICIENT_DATA,
        }:
            status_store.record_failure(
                attempted_at=normalized_as_of,
                reason="incomplete_monitoring_evidence",
            )
            return _failure(
                as_of=normalized_as_of,
                category="incomplete_monitoring_evidence",
                exit_code=AwsRunExitCode.INVALID_OR_INCOMPLETE_EVIDENCE,
                published=published,
                report_fields=report_fields,
            )

        stage = "run_status"
        status_store.record_success(
            completed_at=normalized_as_of,
            report_id=report.report_id,
        )
        return AwsRunExecution(
            exit_code=AwsRunExitCode.SUCCEEDED,
            output=AwsRunOutput(
                status="succeeded",
                category="monitoring_cycle_completed",
                as_of=_canonical_z(normalized_as_of),
                json_key=published.json_key,
                json_sha256=published.json_sha256,
                html_key=published.html_key,
                html_sha256=published.html_sha256,
                latest_updated=published.latest_updated,
                **report_fields,
            ),
        )
    except ClientError as error:
        category = (
            "aws_permission_denied"
            if _client_error_is_access_denied(error)
            else "aws_operation_failed"
        )
        exit_code = AwsRunExitCode.AWS_ACCESS_FAILURE
    except BotoCoreError:
        category = "aws_operation_failed"
        exit_code = AwsRunExitCode.AWS_ACCESS_FAILURE
    except (OSError, TimeoutError):
        category = (
            "persistence_failure"
            if stage in {"report_persistence", "run_status", "telemetry"}
            else "storage_failure"
        )
        exit_code = AwsRunExitCode.PERSISTENCE_FAILURE
    except (TypeError, ValueError):
        if stage == "configuration":
            category = "invalid_aws_run_configuration"
            exit_code = AwsRunExitCode.INVALID_CONFIGURATION
        else:
            category = "invalid_monitoring_evidence"
            exit_code = AwsRunExitCode.INVALID_OR_INCOMPLETE_EVIDENCE
    except RuntimeError:
        category = "persistence_failure"
        exit_code = AwsRunExitCode.PERSISTENCE_FAILURE

    if status_store is not None:
        try:
            status_store.record_failure(attempted_at=normalized_as_of, reason=category)
        except (BotoCoreError, ClientError, OSError, RuntimeError, TypeError, ValueError):
            category = "run_status_persistence_failure"
            exit_code = AwsRunExitCode.PERSISTENCE_FAILURE
    return _failure(
        as_of=normalized_as_of,
        category=category,
        exit_code=exit_code,
        published=published,
        report_fields=report_fields,
    )


def parse_optional_utc(value: str | None, *, name: str) -> datetime | None:
    if value is None:
        return None
    return parse_utc_timestamp(value, name=name)


def utc_now() -> datetime:
    """Small injected-clock boundary for the scheduled one-shot command."""

    return datetime.now(UTC)
