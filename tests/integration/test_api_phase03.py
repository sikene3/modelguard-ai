"""Integration tests for readiness, access modes, limits, timeouts, and redaction."""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from modelguard.api.main import create_app
from modelguard.core.config import ApiAccessMode, AppEnvironment, EventSink, Settings
from modelguard.core.logging import configure_json_logging
from modelguard.core.telemetry import PrometheusTelemetry
from modelguard.inference.events import EventSinkWriteResult, SerializedPredictionEvent
from modelguard.inference.loader import VerifiedModelLoader


class RecordingLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, dict[str, object]]] = []

    def info(self, event: str, **fields: object) -> None:
        self.entries.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.entries.append(("warning", event, fields))

    def error(self, event: str, **fields: object) -> None:
        self.entries.append(("error", event, fields))


class StaticLoader:
    def __init__(self, bundle: Any) -> None:
        self.bundle = bundle
        self.calls = 0

    def load(self, settings: Settings) -> Any:
        del settings
        self.calls += 1
        return self.bundle


class SlowEventSink:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.emit_calls = 0
        self.closed = False

    async def emit(self, record: SerializedPredictionEvent) -> EventSinkWriteResult:
        del record
        self.emit_calls += 1
        await asyncio.sleep(self.delay_seconds)
        return EventSinkWriteResult.DISABLED_DROPPED

    async def close(self) -> None:
        self.closed = True


class TrackingModel:
    def __init__(self, delegate: Any, delay_seconds: float) -> None:
        self._delegate = delegate
        self.classes_ = delegate.classes_
        self._delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def predict_proba(self, features: Any) -> Any:
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            time.sleep(self._delay_seconds)
            return self._delegate.predict_proba(features)
        finally:
            with self._lock:
                self.active -= 1


def test_invalid_or_missing_bundle_keeps_liveness_but_fails_readiness(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "corrupt-bundle"
    shutil.copytree(api_settings.model_bundle_path, corrupt)
    (corrupt / "checksums.sha256").write_text("invalid\n", encoding="utf-8")

    async def exercise(bundle_path: Path) -> None:
        logger = RecordingLogger()
        telemetry = PrometheusTelemetry()
        settings = Settings(
            _env_file=None,
            app_env=AppEnvironment.TEST,
            model_bundle_path=bundle_path,
            active_model_version="1.0.0",
        )
        app = create_app(settings, telemetry=telemetry, logger=logger)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                live = await client.get("/health/live")
                ready = await client.get("/health/ready")
                version = await client.get("/version")
                prediction = await client.post("/v1/predict", json=valid_prediction_payload)
                metrics = (await client.get("/metrics")).text

        assert live.status_code == 200
        assert live.json() == {"status": "live"}
        assert ready.status_code == 503
        assert ready.json() == {"status": "not_ready"}
        assert version.status_code == 200
        assert version.json()["model_ready"] is False
        assert version.json()["model_version"] is None
        assert version.json()["manifest_sha256"] is None
        assert prediction.status_code == 503
        assert prediction.json()["code"] == "model_not_ready"
        assert str(bundle_path) not in prediction.text
        assert 'modelguard_model_load_total{outcome="failure"} 1.0' in metrics
        assert 'modelguard_errors_total{kind="model_load"} 1.0' in metrics
        assert all(str(bundle_path) not in json.dumps(entry) for entry in logger.entries)

    asyncio.run(exercise(corrupt))
    asyncio.run(exercise(tmp_path / "missing-bundle"))


def test_aws_https_token_and_http_cidr_only_route_matrix(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    token = "phase03-test-token-with-at-least-32-bytes"
    token_arn = "arn:aws:ssm:us-east-1:123456789012:parameter/modelguard/demo/predict-token"

    async def exercise() -> None:
        https_settings = Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            event_sink=EventSink.DISABLED,
            api_access_mode=ApiAccessMode.HTTPS_BEARER,
            alb_allowed_cidr="203.0.113.8/32",
            prediction_token_ssm_arn=token_arn,
            prediction_bearer_token=SecretStr(token),
            model_bundle_path=api_settings.model_bundle_path,
            active_model_version="1.0.0",
        )
        https_app = create_app(
            https_settings,
            telemetry=PrometheusTelemetry(),
            logger=RecordingLogger(),
        )
        async with https_app.router.lifespan_context(https_app):
            transport = httpx.ASGITransport(app=https_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.get("/health/live")).json() == {"status": "live"}
                assert (await client.get("/health/ready")).json() == {"status": "ready"}
                assert (await client.get("/version")).status_code == 200
                assert (await client.get("/openapi.json")).status_code == 404
                aws_metrics = await client.get("/metrics")

                no_https = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"authorization": f"Bearer {token}"},
                )
                no_token = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"x-forwarded-proto": "https"},
                )
                wrong_token = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={
                        "x-forwarded-proto": "https",
                        "authorization": "Bearer definitely-wrong",
                    },
                )
                valid = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={
                        "x-forwarded-proto": "https",
                        "authorization": f"Bearer {token}",
                    },
                )
                query_token = await client.post(
                    f"/v1/predict?token={token}",
                    json=valid_prediction_payload,
                    headers={
                        "x-forwarded-proto": "https",
                        "authorization": f"Bearer {token}",
                    },
                )

        assert no_https.status_code == 400
        assert no_https.json()["code"] == "https_required"
        assert no_token.status_code == 401
        assert no_token.headers["www-authenticate"] == "Bearer"
        assert wrong_token.status_code == 401
        assert valid.status_code == 200
        assert query_token.status_code == 400
        assert query_token.json()["code"] == "query_parameters_forbidden"
        assert aws_metrics.status_code == 404
        assert aws_metrics.json()["code"] == "not_found"
        assert "modelguard_" not in aws_metrics.text

        fallback_settings = Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            event_sink=EventSink.DISABLED,
            api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
            alb_allowed_cidr="203.0.113.8/32",
            model_bundle_path=api_settings.model_bundle_path,
            active_model_version="1.0.0",
        )
        fallback_app = create_app(
            fallback_settings,
            telemetry=PrometheusTelemetry(),
            logger=RecordingLogger(),
        )
        async with fallback_app.router.lifespan_context(fallback_app):
            transport = httpx.ASGITransport(app=fallback_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                fallback_open = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"x-forwarded-proto": "http"},
                )
                fallback_credential = await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"authorization": f"Bearer {token}"},
                )

        assert fallback_open.status_code == 200
        assert fallback_credential.status_code == 400
        assert fallback_credential.json()["code"] == "credentials_forbidden"

    asyncio.run(exercise())


def test_token_comparison_runs_for_missing_and_presented_credentials(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
    monkeypatch: Any,
) -> None:
    token = "phase03-constant-time-token-value-12345"
    comparisons: list[tuple[bytes, bytes]] = []
    original_compare = __import__("secrets").compare_digest

    def compare_spy(presented: bytes, expected: bytes) -> bool:
        comparisons.append((presented, expected))
        return original_compare(presented, expected)

    monkeypatch.setattr("modelguard.api.dependencies.secrets.compare_digest", compare_spy)
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        event_sink=EventSink.DISABLED,
        api_access_mode=ApiAccessMode.HTTPS_BEARER,
        alb_allowed_cidr="203.0.113.8/32",
        prediction_token_ssm_arn=(
            "arn:aws:ssm:us-east-1:123456789012:parameter/modelguard/demo/predict-token"
        ),
        prediction_bearer_token=SecretStr(token),
        model_bundle_path=api_settings.model_bundle_path,
        active_model_version="1.0.0",
    )

    async def exercise() -> None:
        app = create_app(settings, telemetry=PrometheusTelemetry(), logger=RecordingLogger())
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"x-forwarded-proto": "https"},
                )
                await client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={
                        "x-forwarded-proto": "https",
                        "authorization": f"Bearer {token}",
                    },
                )

    asyncio.run(exercise())
    assert len(comparisons) == 2
    assert comparisons[0] == (b"", token.encode("utf-8"))
    assert comparisons[1] == (token.encode("utf-8"), token.encode("utf-8"))


def test_body_size_checks_declared_and_streamed_bodies(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    settings = api_settings.model_copy(update={"api_max_request_body_bytes": 128})

    async def chunks() -> Any:
        yield b"{" + (b"x" * 80)
        yield b"x" * 80 + b"}"

    async def exercise() -> None:
        app = create_app(settings, telemetry=PrometheusTelemetry(), logger=RecordingLogger())
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                declared = await client.post("/v1/predict", json=valid_prediction_payload)
                streamed = await client.post(
                    "/v1/predict",
                    content=chunks(),
                    headers={"content-type": "application/json"},
                )

        for response in (declared, streamed):
            assert response.status_code == 413
            assert response.json()["code"] == "request_body_too_large"
            assert set(response.json()) == {"code", "message", "request_id"}

    asyncio.run(exercise())


def test_prediction_concurrency_is_bounded_and_excess_waiters_are_rejected(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    verified = VerifiedModelLoader().load(api_settings)
    tracking_model = TrackingModel(verified.model, delay_seconds=0.08)
    tracked_bundle = replace(verified, model=tracking_model)
    settings = api_settings.model_copy(
        update={
            "api_max_concurrency": 2,
            "api_concurrency_wait_timeout_seconds": 0.01,
        }
    )

    async def exercise() -> list[httpx.Response]:
        app = create_app(
            settings,
            model_loader=StaticLoader(tracked_bundle),
            telemetry=PrometheusTelemetry(),
            logger=RecordingLogger(),
        )
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await asyncio.gather(
                    *[client.post("/v1/predict", json=valid_prediction_payload) for _ in range(8)]
                )

    responses = asyncio.run(exercise())
    status_codes = [response.status_code for response in responses]
    assert tracking_model.maximum_active <= 2
    assert status_codes.count(200) == 2
    assert status_codes.count(503) == 6
    assert all(
        response.json().get("code") == "concurrency_limit_reached"
        for response in responses
        if response.status_code == 503
    )


def test_event_sink_timeout_is_observable_fail_open_and_closes_gracefully(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    settings = api_settings.model_copy(update={"event_sink_timeout_seconds": 0.005})
    sink = SlowEventSink(delay_seconds=0.05)
    logger = RecordingLogger()
    telemetry = PrometheusTelemetry()

    async def exercise() -> httpx.Response:
        app = create_app(settings, telemetry=telemetry, logger=logger, event_sink=sink)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post("/v1/predict", json=valid_prediction_payload)

    response = asyncio.run(exercise())
    metrics = telemetry.render_prometheus().decode("utf-8")
    assert response.status_code == 200
    assert sink.emit_calls == 1
    assert sink.closed is True
    assert 'modelguard_event_sink_operations_total{outcome="timeout"} 1.0' in metrics
    assert 'modelguard_errors_total{kind="event_sink"} 1.0' in metrics
    assert any(event == "prediction_event_write_timeout" for _, event, _ in logger.entries)


def test_application_logs_never_include_token_query_header_or_body(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    token = "phase03-redaction-token-value-123456"
    stream = io.StringIO()
    logger = configure_json_logging(
        api_settings.log_level,
        stream=stream,
        sensitive_values=(token,),
    )
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        event_sink=EventSink.DISABLED,
        api_access_mode=ApiAccessMode.HTTPS_BEARER,
        alb_allowed_cidr="203.0.113.8/32",
        prediction_token_ssm_arn=(
            "arn:aws:ssm:us-east-1:123456789012:parameter/modelguard/demo/predict-token"
        ),
        prediction_bearer_token=SecretStr(token),
        model_bundle_path=api_settings.model_bundle_path,
        active_model_version="1.0.0",
    )

    async def exercise() -> None:
        app = create_app(settings, telemetry=PrometheusTelemetry(), logger=logger)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post(
                    f"/v1/predict?access_token={token}",
                    json={**valid_prediction_payload, "amount": 9876.54321},
                    headers={
                        "x-forwarded-proto": "https",
                        "authorization": f"Bearer {token}",
                    },
                )

    asyncio.run(exercise())
    raw_logs = stream.getvalue()
    assert token not in raw_logs
    assert "Bearer" not in raw_logs
    assert "9876.54321" not in raw_logs
    assert "access_token" not in raw_logs
    for line in raw_logs.splitlines():
        json.loads(line)
