"""Dependency-injected API runtime state, inference orchestration, and access checks."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import Depends, Request

from modelguard.api.errors import ApiProblem
from modelguard.api.schemas import PredictionRequest
from modelguard.core.config import ApiAccessMode, Settings
from modelguard.core.logging import StructuredLogger
from modelguard.core.telemetry import ErrorKind, EventSinkOutcome, Telemetry
from modelguard.inference.events import (
    EventSinkWriteError,
    EventSinkWriteResult,
    FirehoseProducerError,
    LocalEventWriteError,
    PredictionEventSink,
    serialize_prediction_event,
    utc_event_time,
)
from modelguard.inference.predictor import Prediction, PredictionError, Predictor
from modelguard.training.bundle import VerifiedBundle

_EVENT_RESULT_OUTCOMES: dict[EventSinkWriteResult, EventSinkOutcome] = {
    EventSinkWriteResult.LOCAL_PERSISTED: "local_persisted",
    EventSinkWriteResult.FIREHOSE_ACCEPTED: "firehose_accepted",
    EventSinkWriteResult.DISABLED_DROPPED: "disabled_dropped",
}


@dataclass(frozen=True)
class ServedPrediction:
    """A scored result and the latency frozen into its event/HTTP contracts."""

    prediction: Prediction
    latency_ms: float


@dataclass
class ApiContainer:
    """Application-local mutable state; no model or client is stored globally."""

    settings: Settings
    telemetry: Telemetry
    logger: StructuredLogger
    event_sink: PredictionEventSink
    inference_executor: ThreadPoolExecutor
    event_id_factory: Callable[[], UUID] = uuid4
    event_clock: Callable[[], datetime] = utc_event_time
    predictor: Predictor | None = None
    accepting_predictions: bool = False

    @property
    def ready(self) -> bool:
        return self.accepting_predictions and self.predictor is not None

    def install_bundle(self, bundle: VerifiedBundle) -> None:
        """Install exactly one verified model during application startup."""

        if self.predictor is not None:
            raise RuntimeError("a model is already installed in this application")
        self.predictor = Predictor(bundle)

    def begin_serving(self) -> None:
        self.accepting_predictions = True

    async def predict(
        self,
        request: PredictionRequest,
        *,
        request_id: UUID,
        prediction_started_at: float,
    ) -> ServedPrediction:
        predictor = self.predictor
        if not self.accepting_predictions or predictor is None:
            self.telemetry.record_error(ErrorKind.NOT_READY)
            self.logger.warning("prediction_rejected_not_ready", request_id=str(request_id))
            raise ApiProblem(
                status_code=503,
                code="model_not_ready",
                message="The prediction model is not ready.",
            )
        features = request.feature_values()
        try:
            future = self.inference_executor.submit(predictor.predict, features)
            # Inspect the thread-safe concurrent future from the event-loop thread. Polling avoids
            # depending on a cross-thread loop wakeup after native training-library lifecycles,
            # while the admission slot still bounds both running and queued inference work.
            while not future.done():
                await asyncio.sleep(0.001)
            prediction = future.result()
        except asyncio.CancelledError:
            if not future.cancel():
                while not future.done():
                    await asyncio.sleep(0.001)
            raise
        except PredictionError as error:
            self.telemetry.record_error(ErrorKind.PREDICTION)
            self.logger.error(
                "prediction_contract_failed",
                request_id=str(request_id),
                exception_type=type(error).__name__,
            )
            raise ApiProblem(
                status_code=500,
                code="prediction_failed",
                message="The prediction could not be completed.",
            ) from error
        latency_ms = round(max((time.perf_counter() - prediction_started_at) * 1_000.0, 0.0), 3)
        served = ServedPrediction(prediction=prediction, latency_ms=latency_ms)
        self.telemetry.record_prediction(prediction.decision.value)
        sink_started = time.perf_counter()
        try:
            record = serialize_prediction_event(
                request_id=request_id,
                features=features,
                prediction=prediction,
                manifest_sha256=predictor.manifest_sha256,
                input_schema_version=predictor.input_schema_version,
                latency_ms=latency_ms,
                event_id_factory=self.event_id_factory,
                clock=self.event_clock,
            )
        except (TypeError, ValueError) as error:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("serialization_failed", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.error(
                "prediction_event_serialization_failed",
                request_id=str(request_id),
                exception_type=type(error).__name__,
            )
            return served

        try:
            write_result = await asyncio.wait_for(
                self.event_sink.emit(record),
                timeout=self.settings.event_sink_timeout_seconds,
            )
        except TimeoutError:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("timeout", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.warning(
                "prediction_event_write_timeout",
                request_id=str(request_id),
                event_id=str(record.event.event_id),
            )
        except LocalEventWriteError as error:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("local_failed", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.error(
                "prediction_event_local_persistence_failed",
                request_id=str(request_id),
                event_id=str(record.event.event_id),
                exception_type=type(error).__name__,
            )
        except FirehoseProducerError as error:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("firehose_producer_failed", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.error(
                "prediction_event_firehose_producer_failed",
                request_id=str(request_id),
                event_id=str(record.event.event_id),
                exception_type=type(error).__name__,
            )
        except EventSinkWriteError as error:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("failure", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.error(
                "prediction_event_sink_failed",
                request_id=str(request_id),
                event_id=str(record.event.event_id),
                exception_type=type(error).__name__,
            )
        except Exception as error:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("failure", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.error(
                "prediction_event_sink_failed",
                request_id=str(request_id),
                event_id=str(record.event.event_id),
                exception_type=type(error).__name__,
            )
        else:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink(_EVENT_RESULT_OUTCOMES[write_result], elapsed)
            if write_result is EventSinkWriteResult.LOCAL_PERSISTED:
                self.logger.info(
                    "prediction_event_local_persisted",
                    request_id=str(request_id),
                    event_id=str(record.event.event_id),
                )
            elif write_result is EventSinkWriteResult.FIREHOSE_ACCEPTED:
                self.logger.info(
                    "prediction_event_firehose_producer_accepted",
                    request_id=str(request_id),
                    event_id=str(record.event.event_id),
                )
            else:
                self.telemetry.record_error(ErrorKind.EVENT_SINK)
                self.logger.warning(
                    "prediction_event_dropped_disabled",
                    request_id=str(request_id),
                    event_id=str(record.event.event_id),
                )
        return served

    async def shutdown(self) -> None:
        """Stop admission and bound future sink cleanup during graceful shutdown."""

        self.accepting_predictions = False
        try:
            await asyncio.wait_for(
                self.event_sink.close(),
                timeout=self.settings.graceful_shutdown_timeout_seconds,
            )
        except TimeoutError:
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.warning("event_sink_shutdown_timeout")
        except Exception as error:
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.error(
                "event_sink_shutdown_failed",
                exception_type=type(error).__name__,
            )
        self.inference_executor.shutdown(wait=True, cancel_futures=True)


async def get_container(request: Request) -> ApiContainer:
    """Resolve the application-local dependency container."""

    return cast(ApiContainer, request.app.state.container)


def get_request_id(request: Request) -> UUID:
    """Resolve the server-generated correlation ID installed by middleware."""

    raw_request_id = getattr(request.state, "request_id", None)
    if isinstance(raw_request_id, str):
        return UUID(raw_request_id)
    return uuid4()


ContainerDependency = Annotated[ApiContainer, Depends(get_container)]


async def enforce_prediction_access(request: Request, container: ContainerDependency) -> None:
    """Enforce the fixed local/HTTPS-token/restricted-HTTP prediction route matrix."""

    request_id = get_request_id(request)
    if request.scope.get("query_string", b""):
        container.telemetry.record_error(ErrorKind.AUTH)
        container.logger.warning("prediction_query_rejected", request_id=str(request_id))
        raise ApiProblem(
            status_code=400,
            code="query_parameters_forbidden",
            message="Prediction query parameters are not accepted.",
        )

    mode = container.settings.api_access_mode
    authorization = request.headers.get("authorization")
    if mode is ApiAccessMode.HTTP_CIDR_ONLY and authorization is not None:
        container.telemetry.record_error(ErrorKind.AUTH)
        container.logger.warning("fallback_credential_rejected", request_id=str(request_id))
        raise ApiProblem(
            status_code=400,
            code="credentials_forbidden",
            message="Credentials are not accepted in CIDR-only HTTP mode.",
        )

    if mode is not ApiAccessMode.HTTPS_BEARER:
        return

    forwarded_protocol = request.headers.get("x-forwarded-proto", "").split(",", maxsplit=1)[0]
    if forwarded_protocol.strip().casefold() != "https":
        container.telemetry.record_error(ErrorKind.TRANSPORT)
        container.logger.warning("prediction_transport_rejected", request_id=str(request_id))
        raise ApiProblem(
            status_code=400,
            code="https_required",
            message="HTTPS is required for token-authenticated prediction.",
        )

    header = authorization or ""
    scheme, separator, credential = header.partition(" ")
    syntax_valid = (
        separator == " "
        and scheme.casefold() == "bearer"
        and bool(credential)
        and credential.strip() == credential
        and not any(character.isspace() for character in credential)
    )
    presented = credential.encode("utf-8") if syntax_valid else b""
    configured_secret = container.settings.prediction_bearer_token
    expected = (
        configured_secret.get_secret_value().encode("utf-8")
        if configured_secret is not None
        else b""
    )
    valid = secrets.compare_digest(presented, expected)
    if not syntax_valid or not valid:
        container.telemetry.record_error(ErrorKind.AUTH)
        container.logger.warning("prediction_auth_rejected", request_id=str(request_id))
        raise ApiProblem(
            status_code=401,
            code="invalid_bearer_token",
            message="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
