"""Injected AWS monitoring boundaries with versioned reads and conditional writes."""

from __future__ import annotations

import gzip
import zlib
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, Protocol, cast

from botocore.exceptions import BotoCoreError, ClientError

from modelguard.core.hashing import sha256_bytes
from modelguard.core.serialization import canonical_json_bytes, validate_strict_json_model
from modelguard.monitoring.events import (
    EventIdentity,
    FrozenRawSnapshot,
    MonitoringWindow,
    freeze_raw_payloads,
    target_identity_from_bundle,
)
from modelguard.monitoring.persistence import (
    AlertDimension,
    AlertMarker,
    AlertNotification,
    AlertSendResult,
    AlertSendStatus,
    AlertSink,
    RunStatusArtifact,
)
from modelguard.monitoring.report import MonitoringReport, render_offline_html
from modelguard.storage.versioned_bundle import (
    ActiveMonitoringPointer,
    SsmTargetSnapshotResolver,
    VersionedBundleLocation,
    download_versioned_bundle,
)
from modelguard.training.bundle import ValidatedBundleMetadata

__all__ = [
    "ActiveMonitoringPointer",
    "SsmTargetSnapshotResolver",
    "VersionedBundleLocation",
    "download_versioned_bundle",
]


class S3Client(Protocol):
    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def list_objects_v2(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class SnsClient(Protocol):
    def publish(self, **kwargs: Any) -> Mapping[str, Any]: ...


class StreamingBody(Protocol):
    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


def _body_bytes(response: Mapping[str, Any], *, maximum_bytes: int = 64 * 1024 * 1024) -> bytes:
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise ValueError("AWS object response lacks a readable body")
    reader = cast(StreamingBody, body)
    try:
        payload = reader.read(maximum_bytes + 1)
    finally:
        with suppress(AttributeError, OSError):
            reader.close()
    if not isinstance(payload, bytes):
        raise ValueError("AWS object body did not return bytes")
    if len(payload) > maximum_bytes:
        raise ValueError("AWS object body exceeds the bounded read limit")
    return payload


@dataclass(frozen=True)
class S3ObjectSnapshot:
    key: str
    version_id: str | None
    etag: str
    content_length: int


PREDICTION_OBJECT_SUFFIXES = (".jsonl.gz",)
MAXIMUM_PREDICTION_HOUR_PREFIXES = 100


def prediction_arrival_hour_prefixes(
    window: MonitoringWindow,
    *,
    root_prefix: str = "predictions/",
    maximum_prefixes: int = MAXIMUM_PREDICTION_HOUR_PREFIXES,
) -> tuple[str, ...]:
    """Return finite UTC arrival-hour prefixes covering the event window through finalization."""

    if (
        not root_prefix
        or root_prefix.startswith("/")
        or not root_prefix.endswith("/")
        or "//" in root_prefix
        or any(ord(character) < 32 for character in root_prefix)
        or maximum_prefixes < 1
    ):
        raise ValueError("prediction arrival-prefix configuration is invalid")
    start = window.start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    final_arrival = window.eligible_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    if final_arrival < start:
        raise ValueError("prediction arrival-prefix window is invalid")
    count = int((final_arrival - start).total_seconds() // 3_600) + 1
    if count > maximum_prefixes:
        raise ValueError("prediction arrival-prefix window exceeds the bounded hour limit")
    return tuple(
        f"{root_prefix}year={hour:%Y}/month={hour:%m}/day={hour:%d}/hour={hour:%H}/"
        for hour in (start + timedelta(hours=index) for index in range(count))
    )


def _enumerate_s3_objects(
    client: S3Client,
    *,
    bucket: str,
    prefixes: tuple[str, ...],
    maximum_objects: int,
    maximum_pages: int = 100,
    maximum_entries: int = 50_000,
) -> list[str]:
    if (
        not prefixes
        or len(set(prefixes)) != len(prefixes)
        or any(not prefix or not prefix.endswith("/") for prefix in prefixes)
        or maximum_objects < 1
        or maximum_pages < 1
        or maximum_entries < 1
    ):
        raise ValueError("S3 prediction enumeration bounds and prefixes must be valid")
    keys: set[str] = set()
    page_count = 0
    entry_count = 0
    for prefix in prefixes:
        token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            page_count += 1
            if page_count > maximum_pages:
                raise ValueError("S3 prediction snapshot exceeds the pagination limit")
            request: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1_000}
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
                entry_count += 1
                if entry_count > maximum_entries:
                    raise ValueError("S3 prediction snapshot exceeds the listing-entry limit")
                if not key.startswith(prefix):
                    raise ValueError("S3 listing returned a key outside the requested prefix")
                if key.endswith(PREDICTION_OBJECT_SUFFIXES):
                    keys.add(key)
                    if len(keys) > maximum_objects:
                        raise ValueError("S3 prediction snapshot exceeds the object-count limit")
            if "IsTruncated" not in response:
                raise ValueError("S3 listing lacks a truncation marker")
            is_truncated = response["IsTruncated"]
            if not isinstance(is_truncated, bool):
                raise ValueError("S3 listing truncation marker must be a boolean")
            if not is_truncated:
                break
            next_token = response.get("NextContinuationToken")
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token == token
                or next_token in seen_tokens
            ):
                raise ValueError("S3 listing pagination token is invalid")
            seen_tokens.add(next_token)
            token = next_token
    return sorted(keys)


def freeze_s3_raw_snapshot(
    client: S3Client,
    *,
    bucket: str,
    prefixes: tuple[str, ...],
    maximum_objects: int = 10_000,
    maximum_object_bytes: int = 64 * 1024 * 1024,
    maximum_snapshot_bytes: int = 256 * 1024 * 1024,
) -> FrozenRawSnapshot:
    """Enumerate once, pin each object by VersionId/ETag, then freeze logical records."""

    objects: list[S3ObjectSnapshot] = []
    total_bytes = 0
    for key in _enumerate_s3_objects(
        client,
        bucket=bucket,
        prefixes=prefixes,
        maximum_objects=maximum_objects,
    ):
        metadata = client.head_object(Bucket=bucket, Key=key)
        etag = metadata.get("ETag")
        version_id = metadata.get("VersionId")
        content_length = metadata.get("ContentLength")
        if not isinstance(etag, str) or not etag:
            raise ValueError("S3 snapshot object lacks an ETag")
        if version_id is not None and not isinstance(version_id, str):
            raise ValueError("S3 snapshot VersionId must be a string when present")
        if not isinstance(content_length, int) or not 0 <= content_length <= maximum_object_bytes:
            raise ValueError("S3 prediction object exceeds its bounded size contract")
        total_bytes += content_length
        if total_bytes > maximum_snapshot_bytes:
            raise ValueError("S3 prediction snapshot exceeds its aggregate size contract")
        objects.append(
            S3ObjectSnapshot(
                key=key,
                version_id=version_id,
                etag=etag,
                content_length=content_length,
            )
        )
    payloads: list[bytes] = []
    decoded_total_bytes = 0
    for item in objects:
        request: dict[str, Any] = {"Bucket": bucket, "Key": item.key}
        if item.version_id is not None:
            request["VersionId"] = item.version_id
        else:
            request["IfMatch"] = item.etag
        response = client.get_object(**request)
        if item.version_id is not None and response.get("VersionId") != item.version_id:
            raise ValueError("S3 prediction response VersionId changed after snapshot")
        if item.version_id is None and response.get("ETag") != item.etag:
            raise ValueError("S3 prediction response ETag changed after snapshot")
        payload = _body_bytes(response, maximum_bytes=maximum_object_bytes)
        if len(payload) != item.content_length:
            raise ValueError("S3 prediction response length changed after snapshot")
        if item.key.endswith(".gz"):
            try:
                with gzip.GzipFile(fileobj=BytesIO(payload), mode="rb") as compressed:
                    payload = compressed.read(maximum_object_bytes + 1)
            except (gzip.BadGzipFile, EOFError, zlib.error) as error:
                raise ValueError("S3 prediction object is not valid GZIP JSONL") from error
            if len(payload) > maximum_object_bytes:
                raise ValueError("decompressed prediction object exceeds the size limit")
        decoded_total_bytes += len(payload)
        if decoded_total_bytes > maximum_snapshot_bytes:
            raise ValueError("decoded prediction snapshot exceeds the aggregate size contract")
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
    alert_failure_count: int = 0


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
        latest_decided = False
        claims: list[tuple[str, str, AlertNotification]] = []
        for _ in range(5):
            current = self._get(latest_key)
            previous = (
                validate_strict_json_model(current[0], MonitoringReport)
                if current is not None
                else None
            )
            if previous is not None and report.window.end <= previous.window.end:
                latest_decided = True
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
            latest_decided = True
            # Only the publisher that wins the conditional latest update evaluates and claims
            # transitions. Claims are still durable before any SNS call, but a losing contender
            # cannot strand an unsent marker and suppress the winner.
            claims = self._claim_markers(report, previous)
            break

        if not latest_decided:
            raise RuntimeError("S3 latest report conditional update did not converge")

        sink = alert_sink
        marker_keys: list[str] = []
        alert_failure_count = 0
        if latest_updated:
            for key, etag, notification in claims:
                result = (
                    sink.send(notification)
                    if sink is not None
                    else AlertSendResult(status=AlertSendStatus.NOT_CONFIGURED)
                )
                marker = AlertMarker(notification=notification, send_result=result)
                if result.status is AlertSendStatus.FAILED:
                    alert_failure_count += 1
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
            alert_failure_count=alert_failure_count,
        )


class S3RunStateStore:
    """Conditionally persist the latest one-shot attempt without losing prior success."""

    def __init__(self, client: S3Client, *, bucket: str, prefix: str = "monitoring/") -> None:
        if not bucket or prefix.startswith("/") or not prefix.endswith("/"):
            raise ValueError("S3 run-state bucket/prefix configuration is invalid")
        self._client = client
        self._bucket = bucket
        self._key = f"{prefix}run-status.json"

    def _read(self) -> tuple[RunStatusArtifact, str] | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._key)
        except ClientError as error:
            if _is_missing(error):
                return None
            raise
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise ValueError("S3 run-status object lacks ETag")
        return validate_strict_json_model(_body_bytes(response), RunStatusArtifact), etag

    def _write_if_current(self, status: RunStatusArtifact) -> bool:
        for _ in range(5):
            current = self._read()
            candidate = status
            if current is not None:
                artifact, etag = current
                if status.latest_attempt_at < artifact.latest_attempt_at:
                    return False
                if status.latest_attempt_state == "failed":
                    candidate = status.model_copy(
                        update={
                            "latest_success_at": artifact.latest_success_at,
                            "latest_report_id": artifact.latest_report_id,
                        }
                    )
                payload = canonical_json_bytes(candidate) + b"\n"
                if status.latest_attempt_at == artifact.latest_attempt_at:
                    if canonical_json_bytes(artifact) + b"\n" != payload:
                        raise ValueError("same-time AWS run-status attempts conflict")
                    return False
                condition: dict[str, str] = {"IfMatch": etag}
            else:
                payload = canonical_json_bytes(candidate) + b"\n"
                condition = {"IfNoneMatch": "*"}
            try:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=self._key,
                    Body=payload,
                    ContentType="application/json",
                    **condition,
                )
                return True
            except ClientError as error:
                if not _is_precondition(error):
                    raise
        raise RuntimeError("S3 run-status conditional update did not converge")

    def record_success(self, *, completed_at: datetime, report_id: str) -> bool:
        return self._write_if_current(
            RunStatusArtifact(
                latest_attempt_state="succeeded",
                latest_attempt_at=completed_at,
                latest_success_at=completed_at,
                latest_report_id=report_id,
                failure_reason=None,
            )
        )

    def record_failure(self, *, attempted_at: datetime, reason: str) -> bool:
        return self._write_if_current(
            RunStatusArtifact(
                latest_attempt_state="failed",
                latest_attempt_at=attempted_at,
                latest_success_at=None,
                latest_report_id=None,
                failure_reason=reason,
            )
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
