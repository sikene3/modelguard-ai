"""Dependency-injected API runtime state, inference orchestration, and access checks."""

from __future__ import annotations

import asyncio
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import Depends, Request

from modelguard.api.errors import ApiProblem
from modelguard.api.schemas import PredictionRequest
from modelguard.core.config import ApiAccessMode, Settings
from modelguard.core.logging import StructuredLogger
from modelguard.core.telemetry import ErrorKind, Telemetry
from modelguard.inference.events import PredictionEventSink
from modelguard.inference.predictor import Prediction, PredictionError, Predictor
from modelguard.training.bundle import VerifiedBundle


@dataclass
class ApiContainer:
    """Application-local mutable state; no model or client is stored globally."""

    settings: Settings
    telemetry: Telemetry
    logger: StructuredLogger
    event_sink: PredictionEventSink
    inference_executor: ThreadPoolExecutor
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

    async def predict(self, request: PredictionRequest, *, request_id: UUID) -> Prediction:
        predictor = self.predictor
        if not self.accepting_predictions or predictor is None:
            self.telemetry.record_error(ErrorKind.NOT_READY)
            self.logger.warning("prediction_rejected_not_ready", request_id=str(request_id))
            raise ApiProblem(
                status_code=503,
                code="model_not_ready",
                message="The prediction model is not ready.",
            )
        try:
            future = self.inference_executor.submit(predictor.predict, request.feature_values())
            # Await the worker without polling the event loop. If the requester disconnects, keep
            # the admission slot until already-running CPU work completes so cancellation cannot
            # create an unbounded executor backlog.
            prediction = await asyncio.wrap_future(future)
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

        self.telemetry.record_prediction(prediction.decision.value)
        sink_started = time.perf_counter()
        try:
            await asyncio.wait_for(
                self.event_sink.emit(prediction),
                timeout=self.settings.event_sink_timeout_seconds,
            )
        except TimeoutError:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("timeout", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.warning("event_sink_timeout", request_id=str(request_id))
        except Exception as error:
            elapsed = time.perf_counter() - sink_started
            self.telemetry.record_event_sink("failure", elapsed)
            self.telemetry.record_error(ErrorKind.EVENT_SINK)
            self.logger.error(
                "event_sink_failed",
                request_id=str(request_id),
                exception_type=type(error).__name__,
            )
        else:
            self.telemetry.record_event_sink("success", time.perf_counter() - sink_started)
        return prediction

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
