"""Mock-only AWS target, versioned input, report, SNS, and conditional-write tests."""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from modelguard.core.serialization import canonical_json_bytes
from modelguard.monitoring.aws import (
    ActiveMonitoringPointer,
    S3ReportStore,
    SnsAlertSink,
    SsmTargetSnapshotResolver,
    VersionedBundleLocation,
    download_versioned_bundle,
    freeze_s3_raw_snapshot,
    pointer_matches_metadata,
)
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.events import EventIdentity, freeze_raw_payloads
from modelguard.monitoring.persistence import AlertNotification, AlertSendStatus
from modelguard.monitoring.report import MonitoringReport
from modelguard.monitoring.service import LocalMonitoringRunSpec, run_local_monitoring
from modelguard.monitoring.state import DriftState
from modelguard.training.bundle import EXPECTED_FILENAMES, ValidatedBundleMetadata


def _error(code: str, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "sanitized fake"},
            "ResponseMetadata": {"HTTPStatusCode": 412 if code == "PreconditionFailed" else 404},
        },
        operation,
    )


def _pointer(
    target: EventIdentity,
    *,
    bucket: str = "modelguard-test-bucket",
) -> ActiveMonitoringPointer:
    return ActiveMonitoringPointer(
        target_identity=target,
        bundle=VersionedBundleLocation(
            bucket=bucket,
            key_prefix="model-bundles/1.0.0/",
            object_version_ids={name: f"version-{name}" for name in EXPECTED_FILENAMES},
        ),
    )


class FakeSsm:
    def __init__(self, pointer: ActiveMonitoringPointer) -> None:
        self.pointer = pointer
        self.calls: list[dict[str, object]] = []

    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        return {"Parameter": {"Value": self.pointer.model_dump_json()}}


def test_ssm_target_is_snapshotted_exactly_once_and_strictly_versioned(
    monitoring_target: EventIdentity,
) -> None:
    client = FakeSsm(_pointer(monitoring_target))
    resolver = SsmTargetSnapshotResolver(client, parameter_name="/modelguard/active-model")

    assert resolver.resolve_once() is resolver.resolve_once()
    assert resolver.resolve_once().target_identity == monitoring_target
    assert client.calls == [{"Name": "/modelguard/active-model", "WithDecryption": False}]
    with pytest.raises(ValueError, match="version every exact bundle object"):
        VersionedBundleLocation(
            bucket="modelguard-test-bucket",
            key_prefix="model-bundles/1.0.0/",
            object_version_ids={"manifest.json": "one"},
        )


class VersionedBundleS3:
    def __init__(self, bundle_path: Path) -> None:
        self.bundle_path = bundle_path
        self.calls: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        filename = str(kwargs["Key"]).rsplit("/", 1)[-1]
        assert kwargs["VersionId"] == f"version-{filename}"
        return {"Body": BytesIO((self.bundle_path / filename).read_bytes())}


def test_historical_bundle_download_uses_every_exact_version_then_verifies_identity(
    tmp_path: Path,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    client = VersionedBundleS3(monitoring_metadata.path)
    pointer = _pointer(monitoring_target)
    downloaded = download_versioned_bundle(client, pointer, tmp_path / "downloaded")

    assert downloaded.identity == monitoring_metadata.identity
    assert pointer_matches_metadata(pointer, downloaded)
    assert len(client.calls) == len(EXPECTED_FILENAMES)


class SnapshotS3:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.get_calls: list[dict[str, Any]] = []

    def list_objects_v2(self, **kwargs: Any) -> Mapping[str, Any]:
        del kwargs
        return {
            "Contents": [{"Key": key} for key in reversed(self.payloads)],
            "IsTruncated": False,
        }

    def head_object(self, **kwargs: Any) -> Mapping[str, Any]:
        return {"ETag": f'"etag-{kwargs["Key"]}"', "VersionId": f"version-{kwargs['Key']}"}

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.get_calls.append(kwargs)
        return {"Body": BytesIO(self.payloads[str(kwargs["Key"])])}


def test_s3_raw_snapshot_pins_versions_decompresses_and_ignores_repartitioning() -> None:
    first = b'{"row":1}\n'
    second = b'{"row":2}\n'
    client = SnapshotS3(
        {
            "predictions/b.jsonl.gz": gzip.compress(second, mtime=0),
            "predictions/a.jsonl": first,
        }
    )
    snapshot = freeze_s3_raw_snapshot(
        client,
        bucket="modelguard-events",
        prefix="predictions/",
    )

    assert snapshot.digest == freeze_raw_payloads([second + first]).digest
    assert len(snapshot.records) == 2
    assert all("VersionId" in call and "IfMatch" not in call for call in client.get_calls)


class ConditionalS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.counter = 0
        self.put_calls: list[dict[str, Any]] = []

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        key = str(kwargs["Key"])
        if key not in self.objects:
            raise _error("NoSuchKey", "GetObject")
        body, etag = self.objects[key]
        return {"Body": BytesIO(body), "ETag": etag}

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.put_calls.append(kwargs)
        key = str(kwargs["Key"])
        current = self.objects.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise _error("PreconditionFailed", "PutObject")
        if "IfMatch" in kwargs and (current is None or current[1] != kwargs["IfMatch"]):
            raise _error("PreconditionFailed", "PutObject")
        self.counter += 1
        etag = f'"etag-{self.counter}"'
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        self.objects[key] = (body, etag)
        return {"ETag": etag}


def _service_report(
    tmp_path: Path,
    *,
    hour: int,
    event_factory: Any,
    target: EventIdentity,
    metadata: ValidatedBundleMetadata,
) -> MonitoringReport:
    window_end = datetime(2026, 1, 1, hour, tzinfo=UTC)
    event_dir = tmp_path / f"events-{hour}"
    event_dir.mkdir()
    event = event_factory(hour, window_end - timedelta(minutes=30))
    (event_dir / "events.jsonl").write_bytes(canonical_json_bytes(event) + b"\n")
    result = run_local_monitoring(
        LocalMonitoringRunSpec(
            bundle_path=metadata.path,
            event_directory=event_dir,
            report_directory=tmp_path / f"local-reports-{hour}",
            target_identity=target,
            window_end=window_end,
            as_of=window_end + timedelta(minutes=10),
        ),
        config=MonitoringConfig(minimum_accepted_events=1),
    )
    return result.report


def test_s3_history_is_create_only_and_latest_uses_conditional_monotonic_updates(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    older = _service_report(
        tmp_path,
        hour=1,
        event_factory=monitoring_event_factory,
        target=monitoring_target,
        metadata=monitoring_metadata,
    )
    newer = _service_report(
        tmp_path,
        hour=2,
        event_factory=monitoring_event_factory,
        target=monitoring_target,
        metadata=monitoring_metadata,
    )
    client = ConditionalS3()
    store = S3ReportStore(client, bucket="modelguard-reports")

    first = store.publish(older)  # type: ignore[arg-type]
    second = store.publish(newer)  # type: ignore[arg-type]
    repeated = store.publish(newer)  # type: ignore[arg-type]
    historical = store.publish(older)  # type: ignore[arg-type]

    assert first.latest_updated and second.latest_updated
    assert not repeated.latest_updated and not historical.latest_updated
    latest = client.objects["monitoring/latest.json"][0]
    assert json_report_id(latest) == newer.report_id
    history_puts = [call for call in client.put_calls if "/history/" in str(call["Key"])]
    assert all(call.get("IfNoneMatch") == "*" for call in history_puts)
    latest_puts = [call for call in client.put_calls if call["Key"] == "monitoring/latest.json"]
    assert latest_puts[0].get("IfNoneMatch") == "*"
    assert "IfMatch" in latest_puts[1]


def json_report_id(payload: bytes) -> str:
    value = json.loads(payload)
    return str(value["report_id"])


class FakeSns:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise _error("AccessDenied", "Publish")
        return {"MessageId": "message-1"}


def test_sns_alert_outcomes_are_bounded_and_do_not_expose_provider_text() -> None:
    notification = AlertNotification(
        report_id="a" * 64,
        window_end=datetime(2026, 1, 1, 1, tzinfo=UTC),
        dimension="drift",  # type: ignore[arg-type]
        previous_state="healthy",
        current_state="degraded",
        message="review report",
    )
    success_client = FakeSns()
    success = SnsAlertSink(success_client, topic_arn="arn:aws:sns:us-east-1:123:alerts").send(
        notification
    )
    failure = SnsAlertSink(FakeSns(fail=True), topic_arn="arn:aws:sns:us-east-1:123:alerts").send(
        notification
    )

    assert success.status is AlertSendStatus.SENT
    assert success.provider_message_id == "message-1"
    assert success_client.calls[0]["Subject"] == "ModelGuard drift transition"
    assert failure.status is AlertSendStatus.FAILED
    assert failure.failure_category == "sns_provider_failure"
    assert "AccessDenied" not in failure.model_dump_json()


def test_s3_transition_marker_is_conditional_records_outcome_and_suppresses_retry(
    tmp_path: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    healthy_source = _service_report(
        tmp_path,
        hour=1,
        event_factory=monitoring_event_factory,
        target=monitoring_target,
        metadata=monitoring_metadata,
    )
    healthy = healthy_source.model_copy(
        update={
            "states": healthy_source.states.model_copy(update={"drift": DriftState.HEALTHY}),
            "drift": healthy_source.drift.model_copy(
                update={"state": DriftState.HEALTHY, "reason": "storage_test_baseline"}
            ),
        }
    )
    degraded = _service_report(
        tmp_path,
        hour=2,
        event_factory=monitoring_event_factory,
        target=monitoring_target,
        metadata=monitoring_metadata,
    )
    assert degraded.states.drift is DriftState.DEGRADED

    client = ConditionalS3()
    sns = FakeSns()
    sink = SnsAlertSink(sns, topic_arn="arn:aws:sns:us-east-1:123:alerts")
    store = S3ReportStore(client, bucket="modelguard-reports")
    store.publish(healthy)
    incident = store.publish(degraded, alert_sink=sink)
    repeated = store.publish(degraded, alert_sink=sink)

    marker_key = f"monitoring/alerts/drift-{degraded.report_id}.json"
    marker = json.loads(client.objects[marker_key][0])
    marker_puts = [call for call in client.put_calls if call["Key"] == marker_key]
    assert incident.alert_marker_keys == (marker_key,)
    assert repeated.alert_marker_keys == ()
    assert marker["send_result"]["status"] == "sent"
    assert marker_puts[0]["IfNoneMatch"] == "*"
    assert "IfMatch" in marker_puts[1]
    assert len(sns.calls) == 1
