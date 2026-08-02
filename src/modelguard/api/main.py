"""FastAPI application factory with explicit startup/readiness behavior."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from modelguard.api.dependencies import ApiContainer, get_request_id
from modelguard.api.errors import ApiProblem
from modelguard.api.middleware import OperationalMiddleware
from modelguard.api.routes import router
from modelguard.core.config import AppEnvironment, Settings, load_settings
from modelguard.core.logging import StructuredLogger, configure_json_logging
from modelguard.core.telemetry import ErrorKind, Telemetry, build_telemetry
from modelguard.inference.events import (
    FirehoseClient,
    PredictionEventSink,
    build_prediction_event_sink,
)
from modelguard.inference.loader import (
    ModelLoader,
    ModelLoadError,
    ModelLoadFailure,
    VerifiedModelLoader,
)


def _error_content(*, code: str, message: str, request_id: UUID) -> dict[str, str]:
    return {"code": code, "message": message, "request_id": str(request_id)}


def create_app(
    settings: Settings | None = None,
    *,
    model_loader: ModelLoader | None = None,
    telemetry: Telemetry | None = None,
    logger: StructuredLogger | None = None,
    event_sink: PredictionEventSink | None = None,
    firehose_client: FirehoseClient | None = None,
    request_id_factory: Callable[[], UUID] | None = None,
    event_id_factory: Callable[[], UUID] | None = None,
    event_clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Construct an isolated service instance whose dependencies can be tested directly."""

    resolved_settings = settings or load_settings()
    configured_secret = resolved_settings.prediction_bearer_token
    sensitive_values = (
        (configured_secret.get_secret_value(),) if configured_secret is not None else ()
    )
    resolved_logger = logger or configure_json_logging(
        resolved_settings.log_level,
        sensitive_values=sensitive_values,
    )
    resolved_telemetry = telemetry or build_telemetry(resolved_settings)
    resolved_loader = model_loader or VerifiedModelLoader()
    resolved_event_sink = (
        event_sink
        if event_sink is not None
        else build_prediction_event_sink(
            resolved_settings,
            firehose_client=firehose_client,
        )
    )
    container = ApiContainer(
        settings=resolved_settings,
        telemetry=resolved_telemetry,
        logger=resolved_logger,
        event_sink=resolved_event_sink,
        inference_executor=ThreadPoolExecutor(
            max_workers=resolved_settings.api_inference_workers,
            thread_name_prefix="modelguard-inference",
        ),
    )
    if event_id_factory is not None:
        container.event_id_factory = event_id_factory
    if event_clock is not None:
        container.event_clock = event_clock

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        load_started = time.perf_counter()
        resolved_logger.info("model_load_started")
        try:
            bundle = resolved_loader.load(resolved_settings)
            container.install_bundle(bundle)
        except ModelLoadError as error:
            elapsed = time.perf_counter() - load_started
            resolved_telemetry.record_model_load("failure", elapsed)
            resolved_telemetry.record_error(ErrorKind.MODEL_LOAD)
            resolved_logger.error("model_load_failed", reason=error.reason.value)
        except Exception as error:
            elapsed = time.perf_counter() - load_started
            resolved_telemetry.record_model_load("failure", elapsed)
            resolved_telemetry.record_error(ErrorKind.MODEL_LOAD)
            resolved_logger.error(
                "model_load_failed",
                reason=ModelLoadFailure.UNEXPECTED_FAILURE.value,
                exception_type=type(error).__name__,
            )
        else:
            elapsed = time.perf_counter() - load_started
            resolved_telemetry.record_model_load("success", elapsed)
            predictor = container.predictor
            if predictor is None:
                raise RuntimeError("installed model is unexpectedly unavailable")
            resolved_logger.info(
                "model_load_succeeded",
                model_version=predictor.model_version,
                manifest_sha256=predictor.manifest_sha256,
                latency_ms=round(elapsed * 1_000.0, 3),
            )
        container.begin_serving()
        try:
            yield
        finally:
            resolved_logger.info("graceful_shutdown_started")
            await container.shutdown()
            resolved_logger.info("graceful_shutdown_completed")

    expose_docs = resolved_settings.app_env is not AppEnvironment.AWS
    application = FastAPI(
        title="ModelGuard AI Inference API",
        version="1.0.0",
        debug=False,
        docs_url="/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if expose_docs else None,
        lifespan=lifespan,
    )
    application.state.container = container
    if request_id_factory is None:
        application.add_middleware(
            OperationalMiddleware,
            maximum_body_bytes=resolved_settings.api_max_request_body_bytes,
            maximum_prediction_concurrency=resolved_settings.api_max_concurrency,
            concurrency_wait_timeout_seconds=(
                resolved_settings.api_concurrency_wait_timeout_seconds
            ),
            telemetry=resolved_telemetry,
            logger=resolved_logger,
        )
    else:
        application.add_middleware(
            OperationalMiddleware,
            maximum_body_bytes=resolved_settings.api_max_request_body_bytes,
            maximum_prediction_concurrency=resolved_settings.api_max_concurrency,
            concurrency_wait_timeout_seconds=(
                resolved_settings.api_concurrency_wait_timeout_seconds
            ),
            telemetry=resolved_telemetry,
            logger=resolved_logger,
            request_id_factory=request_id_factory,
        )
    application.include_router(router)

    @application.exception_handler(ApiProblem)
    async def handle_api_problem(request: Request, error: ApiProblem) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=_error_content(
                code=error.code,
                message=error.public_message,
                request_id=get_request_id(request),
            ),
            headers=error.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        request_id = get_request_id(request)
        resolved_telemetry.record_error(ErrorKind.VALIDATION)
        resolved_logger.warning(
            "request_validation_failed",
            request_id=str(request_id),
            issue_count=len(error.errors()),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_content(
                code="invalid_request",
                message="The request did not satisfy the prediction contract.",
                request_id=request_id,
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        request_id = get_request_id(request)
        resolved_telemetry.record_error(ErrorKind.VALIDATION)
        messages = {
            status.HTTP_404_NOT_FOUND: ("not_found", "The requested resource was not found."),
            status.HTTP_405_METHOD_NOT_ALLOWED: (
                "method_not_allowed",
                "The HTTP method is not allowed for this resource.",
            ),
        }
        code, message = messages.get(
            error.status_code,
            ("http_error", "The request could not be completed."),
        )
        return JSONResponse(
            status_code=error.status_code,
            content=_error_content(code=code, message=message, request_id=request_id),
            headers=error.headers,
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        request_id = get_request_id(request)
        resolved_telemetry.record_error(ErrorKind.PREDICTION)
        resolved_logger.error(
            "unhandled_request_error",
            request_id=str(request_id),
            exception_type=type(error).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_content(
                code="internal_error",
                message="The request could not be completed.",
                request_id=request_id,
            ),
        )

    return application


app = create_app()
