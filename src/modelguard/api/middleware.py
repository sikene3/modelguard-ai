"""ASGI request correlation, body-size, concurrency, metrics, and safe access logging."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from modelguard.core.logging import StructuredLogger
from modelguard.core.telemetry import ErrorKind, Telemetry

_ROUTE_LABELS = {
    "/health/live": "/health/live",
    "/health/ready": "/health/ready",
    "/metrics": "/metrics",
    "/openapi.json": "/openapi.json",
    "/version": "/version",
    "/v1/predict": "/v1/predict",
}
_METHOD_LABELS = frozenset({"GET", "POST"})


class RequestBodyTooLarge(ValueError):
    """Raised before FastAPI receives a body larger than the configured cap."""


class InvalidContentLength(ValueError):
    """Raised for ambiguous or malformed Content-Length metadata."""


def _normalized_route(path: str) -> str:
    return _ROUTE_LABELS.get(path, "unmatched")


def _normalized_method(method: str) -> str:
    return method if method in _METHOD_LABELS else "OTHER"


def _declared_content_length(scope: Scope) -> int | None:
    values = [value for name, value in scope.get("headers", []) if name == b"content-length"]
    if not values:
        return None
    if len(values) != 1:
        raise InvalidContentLength
    raw_value = values[0]
    if not raw_value.isdigit():
        raise InvalidContentLength
    return int(raw_value)


async def _read_bounded_body(receive: Receive, maximum_bytes: int) -> bytes:
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return bytes(body)
        if message["type"] != "http.request":
            continue
        body.extend(message.get("body", b""))
        if len(body) > maximum_bytes:
            raise RequestBodyTooLarge
        if not message.get("more_body", False):
            return bytes(body)


def _replay_body(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


class OperationalMiddleware:
    """Apply bounded request controls without inspecting or logging request values."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        maximum_body_bytes: int,
        maximum_prediction_concurrency: int,
        concurrency_wait_timeout_seconds: float,
        telemetry: Telemetry,
        logger: StructuredLogger,
        request_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._app = app
        self._maximum_body_bytes = maximum_body_bytes
        self._prediction_slots = asyncio.BoundedSemaphore(maximum_prediction_concurrency)
        self._concurrency_wait_timeout_seconds = concurrency_wait_timeout_seconds
        self._telemetry = telemetry
        self._logger = logger
        self._request_id_factory = request_id_factory

    async def _send_problem(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
        request_id: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message, "request_id": request_id},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started = time.perf_counter()
        request_id = str(self._request_id_factory())
        scope.setdefault("state", {})["request_id"] = request_id
        method = _normalized_method(str(scope.get("method", "")))
        route = _normalized_route(str(scope.get("path", "")))
        status_code = 500
        acquired = False

        async def correlated_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            effective_receive = receive
            if route == "/v1/predict" and method == "POST":
                try:
                    declared_length = _declared_content_length(scope)
                    if declared_length is not None and declared_length > self._maximum_body_bytes:
                        raise RequestBodyTooLarge
                    body = await _read_bounded_body(receive, self._maximum_body_bytes)
                except InvalidContentLength:
                    self._telemetry.record_error(ErrorKind.VALIDATION)
                    await self._send_problem(
                        scope,
                        receive,
                        correlated_send,
                        status_code=400,
                        code="invalid_content_length",
                        message="The Content-Length header is invalid.",
                        request_id=request_id,
                    )
                    return
                except RequestBodyTooLarge:
                    self._telemetry.record_error(ErrorKind.BODY_TOO_LARGE)
                    await self._send_problem(
                        scope,
                        receive,
                        correlated_send,
                        status_code=413,
                        code="request_body_too_large",
                        message="The request body exceeds the configured limit.",
                        request_id=request_id,
                    )
                    return
                effective_receive = _replay_body(body)
                try:
                    await asyncio.wait_for(
                        self._prediction_slots.acquire(),
                        timeout=self._concurrency_wait_timeout_seconds,
                    )
                except TimeoutError:
                    self._telemetry.record_error(ErrorKind.CONCURRENCY)
                    await self._send_problem(
                        scope,
                        effective_receive,
                        correlated_send,
                        status_code=503,
                        code="concurrency_limit_reached",
                        message="The prediction service is busy; retry later.",
                        request_id=request_id,
                    )
                    return
                acquired = True
            await self._app(scope, effective_receive, correlated_send)
        finally:
            if acquired:
                self._prediction_slots.release()
            elapsed = time.perf_counter() - started
            self._telemetry.record_http_request(
                method=method,
                route=route,
                status_code=status_code,
                latency_seconds=elapsed,
            )
            self._logger.info(
                "request_completed",
                request_id=request_id,
                method=method,
                route=route,
                status_code=status_code,
                latency_ms=round(elapsed * 1_000.0, 3),
            )
