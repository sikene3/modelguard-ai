"""Typed FastAPI routes for health, version, metrics, and prediction."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from modelguard.api.dependencies import (
    ApiContainer,
    enforce_prediction_access,
    get_container,
    get_request_id,
)
from modelguard.api.errors import ApiProblem
from modelguard.api.schemas import (
    ErrorResponse,
    LiveResponse,
    NotReadyResponse,
    PredictionRequest,
    PredictionResponse,
    ReadyResponse,
    VersionResponse,
)
from modelguard.core.config import AppEnvironment
from modelguard.version import __version__

router = APIRouter()
ContainerDependency = Annotated[ApiContainer, Depends(get_container)]
PredictionAccessDependency = Annotated[None, Depends(enforce_prediction_access)]


@router.get("/health/live", response_model=LiveResponse, tags=["health"])
async def live() -> LiveResponse:
    """Report process liveness without inspecting model state or requiring a token."""

    return LiveResponse()


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": NotReadyResponse}},
    tags=["health"],
)
async def ready(container: ContainerDependency) -> ReadyResponse | JSONResponse:
    """Report whether the one startup model load completed successfully."""

    if container.ready:
        return ReadyResponse()
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=NotReadyResponse().model_dump(mode="json"),
    )


@router.get("/version", response_model=VersionResponse, tags=["metadata"])
async def version(container: ContainerDependency) -> VersionResponse:
    """Expose service and durable model identity without filesystem information."""

    predictor = container.predictor
    return VersionResponse(
        service_version=__version__,
        model_ready=container.ready,
        model_version=predictor.model_version if predictor is not None else None,
        manifest_sha256=predictor.manifest_sha256 if predictor is not None else None,
    )


@router.get("/metrics", include_in_schema=False, tags=["observability"])
async def metrics(container: ContainerDependency) -> Response:
    """Expose Prometheus only in local/test environments."""

    if container.settings.app_env is AppEnvironment.AWS:
        raise ApiProblem(
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
            message="The requested resource was not found.",
        )

    return Response(
        content=container.telemetry.render_prometheus(),
        media_type=container.telemetry.prometheus_content_type,
    )


@router.post(
    "/v1/predict",
    response_model=PredictionResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    tags=["inference"],
)
async def predict(
    prediction_request: PredictionRequest,
    request: Request,
    container: ContainerDependency,
    access: PredictionAccessDependency,
) -> PredictionResponse:
    """Validate, score, threshold, and return one correlated prediction."""

    del access
    started = time.perf_counter()
    request_id = get_request_id(request)
    prediction = await container.predict(prediction_request, request_id=request_id)
    latency_ms = max((time.perf_counter() - started) * 1_000.0, 0.0)
    return PredictionResponse(
        request_id=request_id,
        risk_score=prediction.risk_score,
        decision=prediction.decision,
        model_version=prediction.model_version,
        latency_ms=round(latency_ms, 3),
    )
