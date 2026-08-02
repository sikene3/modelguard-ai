"""Injected AWS monitoring boundaries with versioned reads and conditional writes."""

from __future__ import annotations

import gzip
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field, model_validator

from modelguard.core.hashing import sha256_bytes
from modelguard.core.serialization import StrictArtifactModel, canonical_json_bytes
from modelguard.monitoring.events import (
    EventIdentity,
    FrozenRawSnapshot,
    freeze_raw_payloads,
    target_identity_from_bundle,
    verify_target_identity,
)
from modelguard.monitoring.persistence import (
    AlertDimension,
    AlertMarker,
    AlertNotification,
    AlertSendResult,
    AlertSendStatus,
    AlertSink,
)
from modelguard.monitoring.report import MonitoringReport, render_offline_html
from modelguard.training.bundle import EXPECTED_FILENAMES, ValidatedBundleMetadata, inspect_bundle


class SsmClient(Protocol):
    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]: ...


class S3Client(Protocol):
    def list_objects_v2(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class SnsClient(Protocol):
    def publish(self, **kwargs: Any) -> Mapping[str, Any]: ...


class VersionedBundleLocation(StrictArtifactModel):
    bucket: str = Field(min_length=3)
    key_prefix: str = Field(min_length=1)
    object_version_ids: dict[str, str]

    @model_validator(mode="after")
    def validate_exact_bundle(self) -> VersionedBundleLocation:
        if set(self.object_version_ids) != EXPECTED_FILENAMES:
            raise ValueError("AWS bundle pointer must version every exact bundle object")
        if not all(self.object_version_ids.values()):
            raise ValueError("AWS bundle VersionIds cannot be empty")
        if not self.key_prefix.endswith("/") or self.key_prefix.startswith("/"):
            raise ValueError("bundle key prefix must be relative and end in slash")
        return self


class ActiveMonitoringPointer(StrictArtifactModel):
    pointer_schema_version: Literal["modelguard.active-monitor-target.v1"] = (
        "modelguard.active-monitor-target.v1"
    )
    target_identity: EventIdentity
    bundle: VersionedBundleLocation


class SsmTargetSnapshotResolver:
    """Read and validate the active target once per resolver/run, then return the frozen value."""

    def __init__(self, client: SsmClient, *, parameter_name: str) -> None:
        if not parameter_name:
            raise ValueError("SSM parameter name cannot be empty")
        self._client = client
        self._parameter_name = parameter_name
        self._snapshot: ActiveMonitoringPointer | None = None

    def resolve_once(self) -> ActiveMonitoringPointer:
        if self._snapshot is None:
            response = self._client.get_parameter(
                Name=self._parameter_name,
                WithDecryption=False,
            )
            parameter = response.get("Parameter")
            if not isinstance(parameter, Mapping) or not isinstance(parameter.get("Value"), str):
                raise ValueError("SSM active target response lacks a string pointer value")
            self._snapshot = ActiveMonitoringPointer.model_validate_json(parameter["Value"])
        return self._snapshot


class StreamingBody(Protocol):
    def read(self) -> bytes: ...


def _body_bytes(response: Mapping[str, Any]) -> bytes:
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise ValueError("AWS object response lacks a readable body")
    payload = cast(StreamingBody, body).read()
    if not isinstance(payload, bytes):
        raise ValueError("AWS object body did not return bytes")
    return payload


def _create_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("versioned bundle download made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def download_versioned_bundle(
    client: S3Client,
    pointer: ActiveMonitoringPointer,
    destination: Path,
) -> ValidatedBundleMetadata:
    """Download exact VersionIds, inspect every checksum/contract, and verify the target tuple."""

    destination.mkdir(parents=True, exist_ok=False)
    for filename in sorted(EXPECTED_FILENAMES):
        response = client.get_object(
            Bucket=pointer.bundle.bucket,
            Key=f"{pointer.bundle.key_prefix}{filename}",
            VersionId=pointer.bundle.object_version_ids[filename],
        )
        _create_file(destination / filename, _body_bytes(response))
    metadata = inspect_bundle(destination)
    verify_target_identity(metadata, pointer.target_identity)
    return metadata


@dataclass(frozen=True)
class S3ObjectSnapshot:
    key: str
    version_id: str | None
    etag: str


def _enumerate_s3_objects(client: S3Client, *, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        request: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token is not None:
            request["ContinuationToken"] = token
        response = client.list_objects_v2(**request)
        contents = response.get("Contents", [])
        if not isinstance(contents, list):
            raise ValueError("S3 listing Contents must be a list")
        for item in contents:
            if not isinstance(item, Mapping) or not isinstance(item.get("Key"), str):
                raise ValueError("S3 listing contains an invalid key entry")
            key = item["Key"]
            if key.endswith((".jsonl", ".jsonl.gz")):
                keys.append(key)
        if not response.get("IsTruncated", False):
            break
        next_token = response.get("NextContinuationToken")
        if not isinstance(next_token, str) or not next_token or next_token == token:
            raise ValueError("S3 listing pagination token is invalid")
        token = next_token
    if len(keys) != len(set(keys)):
        raise ValueError("S3 snapshot enumeration returned duplicate keys")
    return sorted(keys)


def freeze_s3_raw_snapshot(
    client: S3Client,
    *,
    bucket: str,
    prefix: str,
) -> FrozenRawSnapshot:
    """Enumerate once, pin each object by VersionId/ETag, then freeze logical records."""

    objects: list[S3ObjectSnapshot] = []
    for key in _enumerate_s3_objects(client, bucket=bucket, prefix=prefix):
        metadata = client.head_object(Bucket=bucket, Key=key)
        etag = metadata.get("ETag")
        version_id = metadata.get("VersionId")
        if not isinstance(etag, str) or not etag:
            raise ValueError("S3 snapshot object lacks an ETag")
        if version_id is not None and not isinstance(version_id, str):
            raise ValueError("S3 snapshot VersionId must be a string when present")
        objects.append(S3ObjectSnapshot(key=key, version_id=version_id, etag=etag))
    payloads: list[bytes] = []
    for item in objects:
        request: dict[str, Any] = {"Bucket": bucket, "Key": item.key}
        if item.version_id is not None:
            request["VersionId"] = item.version_id
        else:
            request["IfMatch"] = item.etag
        payload = _body_bytes(client.get_object(**request))
        if item.key.endswith(".gz"):
            try:
                payload = gzip.decompress(payload)
            except (gzip.BadGzipFile, EOFError) as error:
                raise ValueError("S3 prediction object is not valid GZIP JSONL") from error
        payloads.append(payload)
    return freeze_raw_payloads(payloads)


class SnsAlertSink:
    """Send one claimed transition and reduce provider failures to bounded outcomes."""

    def __init__(self, client: SnsClient, *, topic_arn: str) -> None:
        if not topic_arn:
            raise ValueError("SNS topic ARN cannot be empty")
        self._client = client
        self._topic_arn = topic_arn

    def send(self, notification: AlertNotification) -> AlertSendResult:
        try:
            response = self._client.publish(
                TopicArn=self._topic_arn,
                Subject=f"ModelGuard {notification.dimension.value} transition",
                Message=notification.message,
            )
        except (BotoCoreError, ClientError, TimeoutError):
            return AlertSendResult(
                status=AlertSendStatus.FAILED,
                failure_category="sns_provider_failure",
            )
        message_id = response.get("MessageId")
        if not isinstance(message_id, str) or not message_id:
            return AlertSendResult(
                status=AlertSendStatus.FAILED,
                failure_category="sns_missing_message_id",
            )
        return AlertSendResult(
            status=AlertSendStatus.SENT,
            provider_message_id=message_id,
        )


@dataclass(frozen=True)
class S3PublishedReport:
    json_key: str
    html_key: str
    json_sha256: str
    html_sha256: str
    latest_updated: bool
    alert_marker_keys: tuple[str, ...]


def _client_error_code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def _is_precondition(error: ClientError) -> bool:
    return _client_error_code(error) in {"PreconditionFailed", "412"}


def _is_missing(error: ClientError) -> bool:
    return _client_error_code(error) in {"NoSuchKey", "404", "NotFound"}


def _s3_dimension_states(report: MonitoringReport) -> dict[AlertDimension, tuple[str, str]]:
    return {
        AlertDimension.DATA_QUALITY: (report.states.data_quality.value, "invalid"),
        AlertDimension.DRIFT: (report.states.drift.value, "degraded"),
        AlertDimension.PERFORMANCE: (report.states.performance.value, "degraded"),
    }


class S3ReportStore:
    """Conditional S3 report/history/latest/transition implementation for AWS mode."""

    def __init__(self, client: S3Client, *, bucket: str, prefix: str = "monitoring/") -> None:
        if not bucket or prefix.startswith("/") or not prefix.endswith("/"):
            raise ValueError("S3 report bucket/prefix configuration is invalid")
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    def _get(self, key: str) -> tuple[bytes, str] | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _is_missing(error):
                return None
            raise
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise ValueError("S3 report object lacks ETag")
        return _body_bytes(response), etag

    def _create_immutable(self, key: str, payload: bytes, content_type: str) -> bool:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=payload,
                ContentType=content_type,
                IfNoneMatch="*",
            )
            return True
        except ClientError as error:
            if not _is_precondition(error):
                raise
        existing = self._get(key)
        if existing is None or existing[0] != payload:
            raise FileExistsError("immutable S3 report identity has different bytes")
        return False

    def _claim_markers(
        self,
        report: MonitoringReport,
        previous: MonitoringReport | None,
    ) -> list[tuple[str, str, AlertNotification]]:
        prior = _s3_dimension_states(previous) if previous is not None else {}
        claims: list[tuple[str, str, AlertNotification]] = []
        for dimension, (current_state, alert_state) in _s3_dimension_states(report).items():
            previous_state = prior[dimension][0] if dimension in prior else None
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
            key = f"{self._prefix}alerts/{dimension.value}-{report.report_id}.json"
            marker = AlertMarker(notification=notification, send_result=None)
            try:
                response = self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=canonical_json_bytes(marker) + b"\n",
                    ContentType="application/json",
                    IfNoneMatch="*",
                )
            except ClientError as error:
                if _is_precondition(error):
                    continue
                raise
            etag = response.get("ETag")
            if not isinstance(etag, str) or not etag:
                raise ValueError("conditional S3 marker claim lacks ETag")
            claims.append((key, etag, notification))
        return claims

    def publish(
        self,
        report: MonitoringReport,
        *,
        alert_sink: AlertSink | None = None,
    ) -> S3PublishedReport:
        json_bytes = canonical_json_bytes(report) + b"\n"
        html_bytes = render_offline_html(report).encode("utf-8")
        window_key = report.window.end.strftime("%Y%m%dT%H%M%SZ")
        json_key = f"{self._prefix}history/{window_key}/{report.report_id}.json"
        html_key = f"{self._prefix}history/{window_key}/{report.report_id}.html"
        self._create_immutable(json_key, json_bytes, "application/json")
        self._create_immutable(html_key, html_bytes, "text/html; charset=utf-8")

        latest_key = f"{self._prefix}latest.json"
        latest_updated = False
        claims: list[tuple[str, str, AlertNotification]] = []
        for _ in range(5):
            current = self._get(latest_key)
            previous = (
                MonitoringReport.model_validate_json(current[0]) if current is not None else None
            )
            if previous is not None and report.window.end <= previous.window.end:
                break
            request: dict[str, Any] = {
                "Bucket": self._bucket,
                "Key": latest_key,
                "Body": json_bytes,
                "ContentType": "application/json",
            }
            if current is None:
                request["IfNoneMatch"] = "*"
            else:
                request["IfMatch"] = current[1]
            try:
                self._client.put_object(**request)
            except ClientError as error:
                if _is_precondition(error):
                    continue
                raise
            latest_updated = True
            # Only the publisher that wins the conditional latest update evaluates and claims
            # transitions. Claims are still durable before any SNS call, but a losing contender
            # cannot strand an unsent marker and suppress the winner.
            claims = self._claim_markers(report, previous)
            break

        sink = alert_sink
        marker_keys: list[str] = []
        if latest_updated:
            for key, etag, notification in claims:
                result = (
                    sink.send(notification)
                    if sink is not None
                    else AlertSendResult(status=AlertSendStatus.NOT_CONFIGURED)
                )
                marker = AlertMarker(notification=notification, send_result=result)
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=canonical_json_bytes(marker) + b"\n",
                    ContentType="application/json",
                    IfMatch=etag,
                )
                marker_keys.append(key)
        return S3PublishedReport(
            json_key=json_key,
            html_key=html_key,
            json_sha256=sha256_bytes(json_bytes),
            html_sha256=sha256_bytes(html_bytes),
            latest_updated=latest_updated,
            alert_marker_keys=tuple(marker_keys),
        )


def target_from_pointer(pointer: ActiveMonitoringPointer) -> EventIdentity:
    """Small explicit accessor used by AWS run orchestration tests."""

    return pointer.target_identity


def pointer_matches_metadata(
    pointer: ActiveMonitoringPointer,
    metadata: ValidatedBundleMetadata,
) -> bool:
    """Prove the event-carried target matches the exact verified downloaded bundle."""

    return pointer.target_identity == target_identity_from_bundle(metadata)
