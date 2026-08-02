"""Unit tests for the Phase 04 event contract and producer sinks."""

from __future__ import annotations

import asyncio
import json
import stat
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from botocore.exceptions import ClientError
from pytest import MonkeyPatch

import modelguard.inference.events as event_module
from modelguard.core.config import EventSink, Settings
from modelguard.inference.events import (
    FIREHOSE_OUTPUT_COMPRESSION,
    FIREHOSE_UTC_ARRIVAL_PREFIX,
    MAX_EVENT_RECORD_BYTES,
    DisabledPredictionEventSink,
    EventSinkWriteResult,
    FirehosePredictionEventSink,
    FirehoseProducerError,
    LocalEventWriteError,
    LocalJsonlPredictionEventSink,
    PredictionEventV1,
    SerializedPredictionEvent,
    build_prediction_event_sink,
    freeze_local_event_snapshot,
    serialize_prediction_event,
)
from modelguard.inference.predictor import Prediction, RiskDecision

FIXED_TIME = datetime(2026, 8, 2, 12, 34, 56, 789000, tzinfo=UTC)
FIXED_EVENT_ID = UUID("00000000-0000-4000-8000-000000000004")
FIXED_REQUEST_ID = UUID("00000000-0000-4000-8000-000000000003")
MANIFEST_SHA256 = "a" * 64


def _record(
    features: Mapping[str, object],
    *,
    event_id: UUID = FIXED_EVENT_ID,
) -> SerializedPredictionEvent:
    return serialize_prediction_event(
        request_id=FIXED_REQUEST_ID,
        features=features,
        prediction=Prediction(
            risk_score=0.8731,
            decision=RiskDecision.HIGH_RISK,
            model_version="1.0.0",
        ),
        manifest_sha256=MANIFEST_SHA256,
        input_schema_version="modelguard.input.v1",
        latency_ms=14.8,
        event_id_factory=lambda: event_id,
        clock=lambda: FIXED_TIME,
    )


def test_event_serialization_is_canonical_utc_newline_json_and_privacy_allowlisted(
    valid_prediction_payload: dict[str, object],
) -> None:
    record = _record(valid_prediction_payload)
    payload: dict[str, Any] = json.loads(record.json_line)

    assert record.json_line.endswith(b"\n")
    assert record.json_line.count(b"\n") == 1
    assert payload == record.event.model_dump(mode="json")
    assert payload["event_schema_version"] == "modelguard.prediction-event.v1"
    assert payload["event_id"] == str(FIXED_EVENT_ID)
    assert payload["request_id"] == str(FIXED_REQUEST_ID)
    assert payload["event_timestamp"] == "2026-08-02T12:34:56.789000Z"
    assert payload["model_version"] == "1.0.0"
    assert payload["bundle_manifest_sha256"] == MANIFEST_SHA256
    assert payload["input_schema_version"] == "modelguard.input.v1"
    assert payload["features"] == valid_prediction_payload
    assert payload["score"] == 0.8731
    assert payload["decision"] == "high_risk"
    assert payload["latency_ms"] == 14.8

    persisted_keys = set(payload) | set(payload["features"])
    assert persisted_keys.isdisjoint(
        {"card_number", "card", "name", "email", "ip", "token", "authorization"}
    )


def test_event_serialization_rejects_records_over_the_producer_bound(
    valid_prediction_payload: dict[str, object],
) -> None:
    oversized_version = f"{'1' * MAX_EVENT_RECORD_BYTES}.0.0"

    with pytest.raises(ValueError, match="exceeds the bounded producer size"):
        serialize_prediction_event(
            request_id=FIXED_REQUEST_ID,
            features=valid_prediction_payload,
            prediction=Prediction(
                risk_score=0.5,
                decision=RiskDecision.LOW_RISK,
                model_version=oversized_version,
            ),
            manifest_sha256=MANIFEST_SHA256,
            input_schema_version="modelguard.input.v1",
            latency_ms=1.0,
            event_id_factory=lambda: FIXED_EVENT_ID,
            clock=lambda: FIXED_TIME,
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 8, 2, 12, 0),
        datetime.fromisoformat("2026-08-02T14:00:00+02:00"),
    ],
)
def test_event_contract_rejects_naive_or_non_utc_timestamps(
    valid_prediction_payload: dict[str, object],
    timestamp: datetime,
) -> None:
    with pytest.raises(ValueError, match="event_timestamp"):
        serialize_prediction_event(
            request_id=FIXED_REQUEST_ID,
            features=valid_prediction_payload,
            prediction=Prediction(
                risk_score=0.5,
                decision=RiskDecision.LOW_RISK,
                model_version="1.0.0",
            ),
            manifest_sha256=MANIFEST_SHA256,
            input_schema_version="modelguard.input.v1",
            latency_ms=1.0,
            clock=lambda: timestamp,
        )


def test_local_sink_uses_single_writer_atomic_lines_and_closed_snapshot(
    tmp_path: Path,
    valid_prediction_payload: dict[str, object],
) -> None:
    records = [
        _record(
            valid_prediction_payload,
            event_id=UUID(f"00000000-0000-4000-8000-{index:012d}"),
        )
        for index in range(1, 5)
    ]
    sink = LocalJsonlPredictionEventSink(tmp_path)

    async def exercise() -> tuple[Path, Path]:
        first_results = await asyncio.gather(*(sink.emit(record) for record in records[:3]))
        assert first_results == [EventSinkWriteResult.LOCAL_PERSISTED] * 3
        active_path = sink.active_path
        assert active_path is not None
        assert active_path.name.endswith(".jsonl.open")
        assert freeze_local_event_snapshot(tmp_path).closed_files == ()

        first_closed = await sink.rotate()
        assert first_closed is not None
        assert not active_path.exists()
        assert first_closed.exists()
        assert stat.S_IMODE(first_closed.stat().st_mode) == 0o600
        assert freeze_local_event_snapshot(tmp_path).closed_files == (first_closed,)

        assert await sink.emit(records[3]) is EventSinkWriteResult.LOCAL_PERSISTED
        second_active = sink.active_path
        assert second_active is not None
        await sink.close()
        second_closed = sink.most_recent_closed_path
        assert second_closed is not None
        assert not second_active.exists()
        return first_closed, second_closed

    first_file, second_file = asyncio.run(exercise())
    assert first_file.read_bytes() == b"".join(record.json_line for record in records[:3])
    assert second_file.read_bytes() == records[3].json_line
    assert freeze_local_event_snapshot(tmp_path).closed_files == tuple(
        sorted((first_file, second_file), key=lambda path: path.name)
    )
    for path in (first_file, second_file):
        for line in path.read_bytes().splitlines(keepends=True):
            assert line.endswith(b"\n")
            PredictionEventV1.model_validate_json(line)


def test_local_sink_wraps_directory_creation_failure(
    tmp_path: Path,
    valid_prediction_payload: dict[str, object],
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocked", encoding="utf-8")
    sink = LocalJsonlPredictionEventSink(blocked_parent / "events")

    async def exercise() -> None:
        with pytest.raises(LocalEventWriteError, match="could not open"):
            await sink.emit(_record(valid_prediction_payload))
        await sink.close()

    asyncio.run(exercise())


class FakeFirehoseClient:
    def __init__(
        self,
        *,
        fail_first: bool = False,
        error_code: str = "AccessDeniedException",
        http_status: int = 403,
    ) -> None:
        self.fail_first = fail_first
        self.error_code = error_code
        self.http_status = http_status
        self.calls: list[tuple[str, bytes]] = []
        self.closed = False

    def put_record(
        self,
        *,
        DeliveryStreamName: str,
        Record: Mapping[str, bytes],
    ) -> Mapping[str, Any]:
        data = Record["Data"]
        self.calls.append((DeliveryStreamName, data))
        if self.fail_first and len(self.calls) == 1:
            raise ClientError(
                {
                    "Error": {"Code": self.error_code, "Message": "sanitized fake failure"},
                    "ResponseMetadata": {"HTTPStatusCode": self.http_status},
                },
                "PutRecord",
            )
        return {"RecordId": f"record-{len(self.calls)}"}

    def close(self) -> None:
        self.closed = True


def test_firehose_retries_reuse_exact_newline_record_and_report_only_producer_acceptance(
    valid_prediction_payload: dict[str, object],
) -> None:
    record = _record(valid_prediction_payload)
    client = FakeFirehoseClient(
        fail_first=True,
        error_code="ServiceUnavailableException",
        http_status=503,
    )
    delays: list[float] = []
    sink = FirehosePredictionEventSink(
        client,
        stream_name="modelguard-demo-predictions",
        max_attempts=2,
        retry_base_delay_seconds=0.025,
        sleeper=delays.append,
    )

    async def exercise() -> EventSinkWriteResult:
        result = await sink.emit(record)
        await sink.close()
        return result

    result = asyncio.run(exercise())

    assert result is EventSinkWriteResult.FIREHOSE_ACCEPTED
    assert delays == [0.025]
    assert len(client.calls) == 2
    assert client.calls[0][0] == client.calls[1][0] == "modelguard-demo-predictions"
    assert client.calls[0][1] is record.json_line
    assert client.calls[1][1] is record.json_line
    assert client.calls[0][1].endswith(b"\n")
    assert FIREHOSE_OUTPUT_COMPRESSION == "GZIP"
    assert "!{timestamp:yyyy}" in FIREHOSE_UTC_ARRIVAL_PREFIX
    assert "model" not in FIREHOSE_UTC_ARRIVAL_PREFIX.casefold()


def test_firehose_nonretryable_failure_is_bounded_and_sanitized(
    valid_prediction_payload: dict[str, object],
) -> None:
    client = FakeFirehoseClient(fail_first=True)
    sink = FirehosePredictionEventSink(
        client,
        stream_name="modelguard-demo-predictions",
        max_attempts=3,
        retry_base_delay_seconds=0.0,
    )

    async def exercise() -> None:
        with pytest.raises(FirehoseProducerError, match="producer request failed") as error:
            await sink.emit(_record(valid_prediction_payload))
        assert "AccessDenied" not in str(error.value)
        await sink.close()

    asyncio.run(exercise())
    assert len(client.calls) == 1


def test_firehose_timeout_returns_promptly_and_does_not_queue_more_records(
    valid_prediction_payload: dict[str, object],
) -> None:
    started = threading.Event()
    completed = threading.Event()
    release = threading.Event()

    class BlockingFirehoseClient(FakeFirehoseClient):
        def put_record(
            self,
            *,
            DeliveryStreamName: str,
            Record: Mapping[str, bytes],
        ) -> Mapping[str, Any]:
            self.calls.append((DeliveryStreamName, Record["Data"]))
            if len(self.calls) == 1:
                started.set()
                release.wait(timeout=1.0)
                completed.set()
            return {"RecordId": f"record-{len(self.calls)}"}

    client = BlockingFirehoseClient()
    sink = FirehosePredictionEventSink(
        client,
        stream_name="modelguard-demo-predictions",
        max_attempts=1,
        retry_base_delay_seconds=0.0,
    )
    first = _record(valid_prediction_payload)
    second = _record(
        valid_prediction_payload,
        event_id=UUID("00000000-0000-4000-8000-000000000005"),
    )

    async def exercise() -> float:
        timeout_started = time.perf_counter()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(sink.emit(first), timeout=0.01)
        elapsed = time.perf_counter() - timeout_started
        assert started.is_set()
        with pytest.raises(FirehoseProducerError, match="still completing"):
            await sink.emit(second)
        assert len(client.calls) == 1
        release.set()
        while not completed.is_set():
            await asyncio.sleep(0.001)
        assert await sink.emit(second) is EventSinkWriteResult.FIREHOSE_ACCEPTED
        await sink.close()
        return elapsed

    try:
        elapsed = asyncio.run(exercise())
    finally:
        release.set()

    assert elapsed < 0.1
    assert client.calls == [
        ("modelguard-demo-predictions", first.json_line),
        ("modelguard-demo-predictions", second.json_line),
    ]


def test_sink_factory_supports_disabled_local_and_bounded_aws_client(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    valid_prediction_payload: dict[str, object],
) -> None:
    disabled = build_prediction_event_sink(Settings(_env_file=None, event_sink=EventSink.DISABLED))
    local = build_prediction_event_sink(
        Settings(_env_file=None, event_sink=EventSink.LOCAL, local_event_dir=tmp_path)
    )
    assert isinstance(disabled, DisabledPredictionEventSink)
    assert isinstance(local, LocalJsonlPredictionEventSink)

    captured: dict[str, object] = {}
    client = FakeFirehoseClient()

    def fake_boto3_client(service_name: str, **kwargs: object) -> FakeFirehoseClient:
        captured["service_name"] = service_name
        captured.update(kwargs)
        return client

    monkeypatch.setattr(event_module.boto3, "client", fake_boto3_client)
    settings = Settings(
        _env_file=None,
        event_sink=EventSink.AWS,
        firehose_stream_name="modelguard-demo-predictions",
        firehose_connect_timeout_seconds=0.11,
        firehose_read_timeout_seconds=0.22,
        firehose_max_attempts=3,
    )
    aws_sink = build_prediction_event_sink(settings)
    assert isinstance(aws_sink, FirehosePredictionEventSink)
    assert captured == {}

    async def exercise_aws_sink() -> None:
        assert await aws_sink.emit(_record(valid_prediction_payload)) is (
            EventSinkWriteResult.FIREHOSE_ACCEPTED
        )
        await aws_sink.close()

    asyncio.run(exercise_aws_sink())
    assert captured["service_name"] == "firehose"
    assert captured["region_name"] == "us-east-1"
    config = captured["config"]
    assert isinstance(config, event_module.Config)
    assert config.connect_timeout == 0.11
    assert config.read_timeout == 0.22
    assert config.retries["total_max_attempts"] == 1
    asyncio.run(local.close())
    assert client.closed is True
