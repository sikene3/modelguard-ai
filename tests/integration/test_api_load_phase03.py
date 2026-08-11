"""Measured local ASGI load gate with explicit Phase 03 targets."""

from __future__ import annotations

import asyncio
import math
import time

import httpx
import pytest

from modelguard.api.main import create_app
from modelguard.core.config import EventSink, Settings
from modelguard.core.telemetry import PrometheusTelemetry

LOAD_REQUESTS = 100
LOAD_CONCURRENCY = 4
MIN_THROUGHPUT_REQUESTS_PER_SECOND = 25.0
MAX_ERROR_RATE = 0.0
MAX_P95_LATENCY_MS = 250.0


class SilentLogger:
    def info(self, event: str, **fields: object) -> None:
        del event, fields

    def warning(self, event: str, **fields: object) -> None:
        del event, fields

    def error(self, event: str, **fields: object) -> None:
        del event, fields


@pytest.mark.integration
@pytest.mark.no_cover
def test_measured_local_prediction_load_targets(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    async def exercise() -> tuple[float, float, float]:
        settings = api_settings.model_copy(
            update={
                "api_max_concurrency": LOAD_CONCURRENCY,
                "api_concurrency_wait_timeout_seconds": 2.0,
                "event_sink": EventSink.DISABLED,
            }
        )
        app = create_app(
            settings,
            telemetry=PrometheusTelemetry(),
            logger=SilentLogger(),
        )
        semaphore = asyncio.Semaphore(LOAD_CONCURRENCY)
        latencies_ms: list[float] = []
        status_codes: list[int] = []

        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://load") as client:
                for _ in range(LOAD_CONCURRENCY):
                    warmup = await client.post("/v1/predict", json=valid_prediction_payload)
                    assert warmup.status_code == 200

                async def send_one() -> None:
                    async with semaphore:
                        started = time.perf_counter()
                        response = await client.post(
                            "/v1/predict",
                            json=valid_prediction_payload,
                        )
                        latencies_ms.append((time.perf_counter() - started) * 1_000.0)
                        status_codes.append(response.status_code)

                started = time.perf_counter()
                await asyncio.gather(*[send_one() for _ in range(LOAD_REQUESTS)])
                elapsed = time.perf_counter() - started

        sorted_latencies = sorted(latencies_ms)
        p95_index = max(math.ceil(0.95 * len(sorted_latencies)) - 1, 0)
        return (
            LOAD_REQUESTS / elapsed,
            sum(code != 200 for code in status_codes) / LOAD_REQUESTS,
            sorted_latencies[p95_index],
        )

    throughput, error_rate, p95_latency_ms = asyncio.run(exercise())
    print(
        "Phase 03 local load result: "
        f"throughput={throughput:.2f} req/s, error_rate={error_rate:.4f}, "
        f"p95={p95_latency_ms:.2f} ms"
    )
    assert throughput >= MIN_THROUGHPUT_REQUESTS_PER_SECOND
    assert error_rate <= MAX_ERROR_RATE
    assert p95_latency_ms <= MAX_P95_LATENCY_MS
