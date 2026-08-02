"""HTTP/OpenAPI contract tests for the Phase 03 inference service."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx

from modelguard.api.main import create_app
from modelguard.core.config import Settings
from modelguard.core.telemetry import PrometheusTelemetry
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


class CountingLoader:
    def __init__(self) -> None:
        self.calls = 0
        self._delegate = VerifiedModelLoader()

    def load(self, settings: Settings) -> Any:
        self.calls += 1
        return self._delegate.load(settings)


def test_prediction_openapi_and_runtime_contract(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    async def exercise() -> None:
        logger = RecordingLogger()
        telemetry = PrometheusTelemetry()
        loader = CountingLoader()
        fixed_request_id = UUID("00000000-0000-4000-8000-000000000003")
        app = create_app(
            api_settings,
            model_loader=loader,
            telemetry=telemetry,
            logger=logger,
            request_id_factory=lambda: fixed_request_id,
        )
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                live = await client.get("/health/live")
                ready = await client.get("/health/ready")
                version = await client.get("/version")
                first = await client.post("/v1/predict", json=valid_prediction_payload)
                second = await client.post("/v1/predict", json=valid_prediction_payload)
                openapi = (await client.get("/openapi.json")).json()
                metrics = await client.get("/metrics")

        assert live.status_code == 200
        assert live.json() == {"status": "live"}
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}
        assert version.status_code == 200
        version_payload = version.json()
        assert set(version_payload) == {
            "service_version",
            "model_ready",
            "model_version",
            "manifest_sha256",
        }
        assert version_payload["service_version"] == "0.1.0"
        assert version_payload["model_ready"] is True
        assert version_payload["model_version"] == "1.0.0"
        assert len(version_payload["manifest_sha256"]) == 64

        for response in (first, second):
            assert response.status_code == 200
            assert response.headers["x-request-id"] == str(fixed_request_id)
            payload = response.json()
            assert set(payload) == {
                "request_id",
                "risk_score",
                "decision",
                "model_version",
                "latency_ms",
            }
            assert payload["request_id"] == str(fixed_request_id)
            assert 0.0 <= payload["risk_score"] <= 1.0
            assert payload["decision"] in {"low_risk", "high_risk"}
            assert payload["model_version"] == "1.0.0"
            assert payload["latency_ms"] >= 0.0
        assert loader.calls == 1

        required_paths = {
            "/health/live",
            "/health/ready",
            "/version",
            "/v1/predict",
        }
        assert required_paths <= set(openapi["paths"])
        request_schema = openapi["components"]["schemas"]["PredictionRequest"]
        assert request_schema["additionalProperties"] is False
        assert request_schema["required"] == list(valid_prediction_payload)
        assert set(request_schema["properties"]) == set(valid_prediction_payload)
        assert metrics.status_code == 200
        assert metrics.headers["content-type"].startswith("text/plain")
        assert "modelguard_api_requests_total" in metrics.text
        assert "modelguard_api_request_latency_seconds" in metrics.text
        assert "modelguard_predictions_total" in metrics.text
        assert "modelguard_model_load_total" in metrics.text
        assert "modelguard_event_sink_operations_total" in metrics.text

    asyncio.run(exercise())


def test_invalid_nonfinite_extra_and_null_http_contracts(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    async def exercise() -> None:
        app = create_app(
            api_settings,
            telemetry=PrometheusTelemetry(),
            logger=RecordingLogger(),
        )
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                invalid_payloads = [
                    {**valid_prediction_payload, "transaction_hour": 2.5},
                    {**valid_prediction_payload, "device_risk_score": None},
                    {**valid_prediction_payload, "unexpected": "must fail"},
                    {**valid_prediction_payload, "country_code": "FR"},
                ]
                responses = [
                    await client.post("/v1/predict", json=payload) for payload in invalid_payloads
                ]
                responses.append(
                    await client.post(
                        "/v1/predict",
                        content=(
                            b'{"amount":NaN,"transaction_hour":2,"velocity_1h":8,'
                            b'"distance_from_home_km":180.0,"device_risk_score":0.82,'
                            b'"merchant_risk_score":0.64,"is_new_device":true,'
                            b'"country_code":"EG","device_type":"mobile"}'
                        ),
                        headers={"content-type": "application/json"},
                    )
                )

        for response in responses:
            assert response.status_code == 422
            assert set(response.json()) == {"code", "message", "request_id"}
            assert response.json()["code"] == "invalid_request"
            UUID(response.json()["request_id"])
            assert "traceback" not in response.text.casefold()
            assert "model-bundles" not in response.text

    asyncio.run(exercise())
