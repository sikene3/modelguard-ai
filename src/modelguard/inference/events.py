"""Versioned, privacy-safe prediction events and pluggable producer sinks."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import BoundedSemaphore
from typing import Annotated, Any, Literal, Protocol, cast
from uuid import UUID, uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)

from modelguard.core.config import EventSink, Settings
from modelguard.core.serialization import canonical_json_bytes
from modelguard.inference.predictor import Prediction, RiskDecision

PredictionEventSchemaVersion = Literal["modelguard.prediction-event.v1"]
PREDICTION_EVENT_SCHEMA_VERSION: PredictionEventSchemaVersion = "modelguard.prediction-event.v1"
MAX_EVENT_RECORD_BYTES = 16_384
FIREHOSE_OUTPUT_COMPRESSION = "GZIP"
FIREHOSE_UTC_ARRIVAL_PREFIX = (
    "predictions/year=!{timestamp:yyyy}/month=!{timestamp:MM}/"
    "day=!{timestamp:dd}/hour=!{timestamp:HH}/"
)


class StrictEventModel(BaseModel):
    """Strict, immutable base for the externally persisted event contract."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


class ApprovedSyntheticFeaturesV1(StrictEventModel):
    """The exact synthetic feature allowlist approved for monitoring."""

    amount: Annotated[float, Field(ge=0.01, le=25_000.0)]
    transaction_hour: Annotated[StrictInt, Field(ge=0, le=23)]
    velocity_1h: Annotated[StrictInt, Field(ge=0, le=30)]
    distance_from_home_km: Annotated[float, Field(ge=0.0, le=1_000.0)]
    device_risk_score: Annotated[float, Field(ge=0.0, le=1.0)]
    merchant_risk_score: Annotated[float, Field(ge=0.0, le=1.0)]
    is_new_device: StrictBool
    country_code: Literal["BR", "DE", "EG", "GB", "IN", "US"]
    device_type: Literal["desktop", "mobile", "tablet"]


class PredictionEventV1(StrictEventModel):
    """Stable v1 JSON contract for one successfully scored prediction."""

    event_schema_version: PredictionEventSchemaVersion
    event_id: UUID
    request_id: UUID
    event_timestamp: AwareDatetime
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    bundle_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_schema_version: str = Field(pattern=r"^modelguard\.input\.v[1-9][0-9]*$")
    features: ApprovedSyntheticFeaturesV1
    score: Annotated[float, Field(ge=0.0, le=1.0)]
    decision: RiskDecision
    latency_ms: Annotated[float, Field(ge=0.0)]

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def require_z_timestamp_text(cls, value: object) -> object:
        """Keep textual inputs aligned with the portable schema's canonical UTC form."""

        if isinstance(value, str):
            if not value.endswith("Z"):
                raise ValueError("event_timestamp text must end with Z")
            return datetime.fromisoformat(f"{value[:-1]}+00:00")
        return value

    @field_validator("event_timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        """Reject merely aware timestamps that are not expressed in UTC."""

        if value.utcoffset() != timedelta(0):
            raise ValueError("event_timestamp must use UTC")
        return value.astimezone(UTC)


@dataclass(frozen=True)
class SerializedPredictionEvent:
    """One immutable event and its one canonical newline-JSON serialization."""

    event: PredictionEventV1
    json_line: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        json_line = canonical_json_bytes(self.event) + b"\n"
        if len(json_line) > MAX_EVENT_RECORD_BYTES:
            raise ValueError("prediction event record exceeds the bounded producer size")
        object.__setattr__(self, "json_line", json_line)


def utc_event_time() -> datetime:
    """Return an aware UTC timestamp for one event."""

    return datetime.now(UTC)


def serialize_prediction_event(
    *,
    request_id: UUID,
    features: Mapping[str, object],
    prediction: Prediction,
    manifest_sha256: str,
    input_schema_version: str,
    latency_ms: float,
    event_id_factory: Callable[[], UUID] = uuid4,
    clock: Callable[[], datetime] = utc_event_time,
) -> SerializedPredictionEvent:
    """Create an ID once and serialize the record once before any producer retry."""

    event = PredictionEventV1(
        event_schema_version=PREDICTION_EVENT_SCHEMA_VERSION,
        event_id=event_id_factory(),
        request_id=request_id,
        event_timestamp=clock(),
        model_version=prediction.model_version,
        bundle_manifest_sha256=manifest_sha256,
        input_schema_version=input_schema_version,
        features=ApprovedSyntheticFeaturesV1.model_validate(dict(features)),
        score=prediction.risk_score,
        decision=prediction.decision,
        latency_ms=latency_ms,
    )
    return SerializedPredictionEvent(event=event)


class EventSinkWriteResult(StrEnum):
    """Positive acceptance and intentional-drop outcomes returned by event sinks."""

    LOCAL_PERSISTED = "local_persisted"
    FIREHOSE_ACCEPTED = "firehose_accepted"
    DISABLED_DROPPED = "disabled_dropped"


class PredictionEventSink(Protocol):
    """Async producer boundary; it cannot control prediction success."""

    async def emit(self, record: SerializedPredictionEvent) -> EventSinkWriteResult:
        """Accept the already serialized record without changing it."""

    async def close(self) -> None:
        """Flush, rotate, or close producer-owned resources."""


class EventSinkWriteError(RuntimeError):
    """Sanitized base for a failed producer operation."""


class LocalEventWriteError(EventSinkWriteError):
    """A local append, durability, or rotation operation failed."""


class FirehoseProducerError(EventSinkWriteError):
    """Firehose did not return producer acceptance within bounded attempts."""


class _SerialWorkerBusyError(RuntimeError):
    """The sole bounded worker is still completing an earlier timed-out operation."""


async def _run_serial_worker[ResultT](
    executor: ThreadPoolExecutor,
    worker_gate: BoundedSemaphore,
    function: Callable[..., ResultT],
    *args: object,
) -> ResultT:
    """Run at most one operation and let cancellation return without queuing more work."""

    if not worker_gate.acquire(blocking=False):
        raise _SerialWorkerBusyError("the serial worker is still completing an operation")
    try:
        future = executor.submit(function, *args)
    except Exception:
        worker_gate.release()
        raise
    release_when_done = False
    try:
        # Polling avoids depending on a cross-thread event-loop wakeup. Some model-training/native
        # library lifecycles can leave that wakeup path unreliable, while the concurrent future's
        # completion state remains safe to inspect from the event-loop thread.
        while not future.done():
            await asyncio.sleep(0.001)
        return future.result()
    except asyncio.CancelledError:
        # A running thread cannot be force-stopped. Leave it as the sole in-flight operation; the
        # gate makes later writes fail fast instead of growing the executor queue.
        release_when_done = True
        future.add_done_callback(lambda _: worker_gate.release())
        future.cancel()
        raise
    finally:
        # Normal completion (including a worker exception) releases on the event-loop thread. This
        # avoids relying on a cross-thread done callback before the awaiting coroutine can proceed.
        if not release_when_done:
            worker_gate.release()


async def _wait_for_serial_worker(worker_gate: BoundedSemaphore) -> None:
    """Wait for the sole in-flight operation during bounded graceful shutdown."""

    while not worker_gate.acquire(blocking=False):
        await asyncio.sleep(0.001)
    worker_gate.release()


class DisabledPredictionEventSink:
    """Explicitly drop events while making that configured outcome observable."""

    async def emit(self, record: SerializedPredictionEvent) -> EventSinkWriteResult:
        del record
        return EventSinkWriteResult.DISABLED_DROPPED

    async def close(self) -> None:
        return None


class NoOpPredictionEventSink(DisabledPredictionEventSink):
    """Backward-compatible name for the now-explicit disabled sink."""


@dataclass(frozen=True)
class LocalEventSnapshot:
    """A frozen enumeration containing only closed event files."""

    closed_files: tuple[Path, ...]


def freeze_local_event_snapshot(directory: Path) -> LocalEventSnapshot:
    """Freeze closed JSONL inputs; active ``.open`` files are never returned."""

    if not directory.exists():
        return LocalEventSnapshot(closed_files=())
    if directory.is_symlink() or not directory.is_dir():
        raise LocalEventWriteError("local event directory must be a non-symlink directory")
    closed_files: list[Path] = []
    for candidate in sorted(directory.glob("*.jsonl"), key=lambda path: path.name):
        if candidate.is_symlink() or not candidate.is_file():
            raise LocalEventWriteError("closed event snapshot contains an unsafe entry")
        closed_files.append(candidate)
    return LocalEventSnapshot(closed_files=tuple(closed_files))


class LocalJsonlPredictionEventSink:
    """Single-writer local sink with one atomic append per durable JSONL record."""

    def __init__(
        self,
        directory: Path,
        *,
        file_id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = utc_event_time,
    ) -> None:
        self._directory = directory
        self._file_id_factory = file_id_factory
        self._clock = clock
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event-file-writer")
        self._worker_gate = BoundedSemaphore(value=1)
        self._operation_lock = asyncio.Lock()
        self._file_descriptor: int | None = None
        self._active_path: Path | None = None
        self._closed_path: Path | None = None
        self._most_recent_closed_path: Path | None = None
        self._closed = False

    @property
    def active_path(self) -> Path | None:
        return self._active_path

    @property
    def most_recent_closed_path(self) -> Path | None:
        return self._most_recent_closed_path

    def _open_unique_file(self) -> None:
        if self._file_descriptor is not None:
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        if self._directory.is_symlink() or not self._directory.is_dir():
            raise LocalEventWriteError("local event directory must be a non-symlink directory")
        timestamp = self._clock().astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        file_id = self._file_id_factory()
        stem = f"prediction-events-{timestamp}-{file_id}"
        active_path = self._directory / f"{stem}.jsonl.open"
        closed_path = self._directory / f"{stem}.jsonl"
        if closed_path.exists() or closed_path.is_symlink():
            raise LocalEventWriteError("unique local event file identity already exists")
        flags = os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_WRONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(active_path, flags, 0o600)
        except OSError as error:
            raise LocalEventWriteError("could not open a unique local event file") from error
        self._file_descriptor = descriptor
        self._active_path = active_path
        self._closed_path = closed_path

    def _append_sync(self, record: SerializedPredictionEvent) -> None:
        self._open_unique_file()
        descriptor = self._file_descriptor
        if descriptor is None:
            raise LocalEventWriteError("local event writer was not opened")
        try:
            written = os.write(descriptor, record.json_line)
            if written != len(record.json_line):
                raise LocalEventWriteError("local event append was incomplete")
            os.fsync(descriptor)
        except OSError as error:
            raise LocalEventWriteError("local event append failed") from error

    def _rotate_sync(self) -> Path | None:
        descriptor = self._file_descriptor
        if descriptor is None:
            return None
        active_path = self._active_path
        closed_path = self._closed_path
        if active_path is None or closed_path is None:
            raise LocalEventWriteError("local event writer paths are unavailable")
        try:
            os.fsync(descriptor)
            os.close(descriptor)
            self._file_descriptor = None
            # Linking publishes the closed name atomically and refuses to replace an existing
            # closed file. The active name is invisible to the monitoring snapshot contract.
            os.link(active_path, closed_path, follow_symlinks=False)
            os.unlink(active_path)
        except OSError as error:
            self._file_descriptor = None
            raise LocalEventWriteError("local event rotation failed") from error
        self._active_path = None
        self._closed_path = None
        self._most_recent_closed_path = closed_path
        return closed_path

    async def emit(self, record: SerializedPredictionEvent) -> EventSinkWriteResult:
        async with self._operation_lock:
            if self._closed:
                raise LocalEventWriteError("local event sink is closed")
            try:
                await _run_serial_worker(
                    self._executor,
                    self._worker_gate,
                    self._append_sync,
                    record,
                )
            except _SerialWorkerBusyError as error:
                raise LocalEventWriteError(
                    "local event writer is still completing a timed-out operation"
                ) from error
        return EventSinkWriteResult.LOCAL_PERSISTED

    async def rotate(self) -> Path | None:
        """Atomically close the active file and publish its final ``.jsonl`` name."""

        async with self._operation_lock:
            if self._closed:
                raise LocalEventWriteError("local event sink is closed")
            try:
                return await _run_serial_worker(
                    self._executor,
                    self._worker_gate,
                    self._rotate_sync,
                )
            except _SerialWorkerBusyError as error:
                raise LocalEventWriteError(
                    "local event writer is still completing a timed-out operation"
                ) from error

    async def close(self) -> None:
        async with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            try:
                await _wait_for_serial_worker(self._worker_gate)
                await _run_serial_worker(
                    self._executor,
                    self._worker_gate,
                    self._rotate_sync,
                )
            finally:
                self._executor.shutdown(wait=False, cancel_futures=True)


class FirehoseClient(Protocol):
    """Small injected subset of the boto3 Firehose client."""

    def put_record(
        self,
        *,
        DeliveryStreamName: str,
        Record: Mapping[str, bytes],
    ) -> Mapping[str, Any]:
        """Submit one producer record."""

    def close(self) -> None:
        """Close SDK-owned connection pools."""


_RETRYABLE_FIREHOSE_CODES = frozenset(
    {
        "InternalFailure",
        "InternalServerError",
        "InternalServerErrorException",
        "ServiceUnavailable",
        "ServiceUnavailableException",
        "Throttling",
        "ThrottlingException",
    }
)
_RETRYABLE_BOTOCORE_ERRORS = (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)


def _is_retryable_firehose_error(error: Exception) -> bool:
    if isinstance(error, ClientError):
        response = error.response
        code = str(response.get("Error", {}).get("Code", ""))
        status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in _RETRYABLE_FIREHOSE_CODES or (
            isinstance(status_code, int) and status_code >= 500
        )
    return isinstance(error, _RETRYABLE_BOTOCORE_ERRORS)


class FirehosePredictionEventSink:
    """Bounded Firehose producer that retries the exact same serialized bytes."""

    def __init__(
        self,
        client: FirehoseClient | None,
        *,
        stream_name: str,
        max_attempts: int,
        retry_base_delay_seconds: float,
        client_factory: Callable[[], FirehoseClient] | None = None,
        owns_client: bool = False,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not stream_name:
            raise ValueError("Firehose stream name cannot be empty")
        if not 1 <= max_attempts <= 5:
            raise ValueError("Firehose max attempts must be in [1, 5]")
        if not 0.0 <= retry_base_delay_seconds <= 1.0:
            raise ValueError("Firehose retry base delay must be in [0, 1]")
        if (client is None) == (client_factory is None):
            raise ValueError("provide exactly one Firehose client or client factory")
        self._client = client
        self._client_factory = client_factory
        self._stream_name = stream_name
        self._max_attempts = max_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._owns_client = owns_client
        self._sleeper = sleeper
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="firehose-producer")
        self._worker_gate = BoundedSemaphore(value=1)
        self._operation_lock = asyncio.Lock()
        self._closed = False

    def _resolve_client(self) -> FirehoseClient:
        client = self._client
        if client is not None:
            return client
        factory = self._client_factory
        if factory is None:
            raise FirehoseProducerError("Firehose client factory is unavailable")
        try:
            client = factory()
        except Exception as error:
            raise FirehoseProducerError("Firehose client initialization failed") from error
        self._client = client
        return client

    def _put_record_sync(self, record: SerializedPredictionEvent) -> None:
        client = self._resolve_client()
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = client.put_record(
                    DeliveryStreamName=self._stream_name,
                    Record={"Data": record.json_line},
                )
            except Exception as error:
                if attempt < self._max_attempts and _is_retryable_firehose_error(error):
                    delay = self._retry_base_delay_seconds * (2 ** (attempt - 1))
                    self._sleeper(delay)
                    continue
                raise FirehoseProducerError("Firehose producer request failed") from error
            record_id = response.get("RecordId")
            if not isinstance(record_id, str) or not record_id:
                raise FirehoseProducerError("Firehose producer response omitted RecordId")
            return
        raise FirehoseProducerError("Firehose producer exhausted its bounded attempts")

    async def emit(self, record: SerializedPredictionEvent) -> EventSinkWriteResult:
        async with self._operation_lock:
            if self._closed:
                raise FirehoseProducerError("Firehose producer is closed")
            try:
                await _run_serial_worker(
                    self._executor,
                    self._worker_gate,
                    self._put_record_sync,
                    record,
                )
            except _SerialWorkerBusyError as error:
                raise FirehoseProducerError(
                    "Firehose producer is still completing a timed-out request"
                ) from error
        return EventSinkWriteResult.FIREHOSE_ACCEPTED

    async def close(self) -> None:
        async with self._operation_lock:
            if self._closed:
                return
            self._closed = True
            try:
                await _wait_for_serial_worker(self._worker_gate)
                client = self._client
                if self._owns_client and client is not None:
                    await _run_serial_worker(
                        self._executor,
                        self._worker_gate,
                        client.close,
                    )
            finally:
                self._executor.shutdown(wait=False, cancel_futures=True)


def _build_bounded_firehose_client(settings: Settings) -> FirehoseClient:
    client_config = Config(
        connect_timeout=settings.firehose_connect_timeout_seconds,
        read_timeout=settings.firehose_read_timeout_seconds,
        retries={"total_max_attempts": 1, "mode": "standard"},
    )
    client = boto3.client(
        "firehose",
        region_name=settings.aws_region,
        config=client_config,
    )
    return cast(FirehoseClient, client)


def build_prediction_event_sink(
    settings: Settings,
    *,
    firehose_client: FirehoseClient | None = None,
) -> PredictionEventSink:
    """Construct the configured sink; fake clients can replace boto3 in tests."""

    if settings.event_sink is EventSink.DISABLED:
        return DisabledPredictionEventSink()
    if settings.event_sink is EventSink.LOCAL:
        return LocalJsonlPredictionEventSink(settings.local_event_dir)
    stream_name = settings.firehose_stream_name
    if stream_name is None:
        raise ValueError("EVENT_SINK=aws requires FIREHOSE_STREAM_NAME")
    return FirehosePredictionEventSink(
        firehose_client,
        stream_name=stream_name,
        max_attempts=settings.firehose_max_attempts,
        retry_base_delay_seconds=settings.firehose_retry_base_delay_seconds,
        client_factory=(
            None
            if firehose_client is not None
            else lambda: _build_bounded_firehose_client(settings)
        ),
        owns_client=firehose_client is None,
    )
