"""Measure a running local API against explicit Phase 03 load targets."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_REQUESTS = 100
DEFAULT_CONCURRENCY = 4
DEFAULT_MIN_THROUGHPUT = 25.0
DEFAULT_MAX_ERROR_RATE = 0.0
DEFAULT_MAX_P95_MS = 250.0
PREDICTION_PAYLOAD: dict[str, object] = {
    "amount": 4200.0,
    "transaction_hour": 2,
    "velocity_1h": 8,
    "distance_from_home_km": 180.0,
    "device_risk_score": 0.82,
    "merchant_risk_score": 0.64,
    "is_new_device": True,
    "country_code": "EG",
    "device_type": "mobile",
}


@dataclass(frozen=True)
class LoadResult:
    requests: int
    concurrency: int
    throughput_requests_per_second: float
    error_rate: float
    p95_latency_ms: float


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--min-throughput", type=float, default=DEFAULT_MIN_THROUGHPUT)
    parser.add_argument("--max-error-rate", type=float, default=DEFAULT_MAX_ERROR_RATE)
    parser.add_argument("--max-p95-ms", type=float, default=DEFAULT_MAX_P95_MS)
    return parser


def _validate_arguments(arguments: argparse.Namespace) -> None:
    parsed_url = urlparse(arguments.url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("the Phase 03 load command accepts only a local HTTP URL")
    if arguments.requests < 1 or arguments.concurrency < 1:
        raise ValueError("requests and concurrency must be positive")
    if arguments.concurrency > arguments.requests:
        raise ValueError("concurrency cannot exceed the request count")
    if arguments.min_throughput <= 0 or arguments.max_p95_ms <= 0:
        raise ValueError("throughput and latency targets must be positive")
    if not 0.0 <= arguments.max_error_rate <= 1.0:
        raise ValueError("max-error-rate must be in [0, 1]")


async def _measure(arguments: argparse.Namespace) -> LoadResult:
    semaphore = asyncio.Semaphore(arguments.concurrency)
    latencies_ms: list[float] = []
    failures = 0
    timeout = httpx.Timeout(5.0)
    limits = httpx.Limits(
        max_connections=arguments.concurrency,
        max_keepalive_connections=arguments.concurrency,
    )
    async with httpx.AsyncClient(base_url=arguments.url, timeout=timeout, limits=limits) as client:
        readiness = await client.get("/health/ready")
        if readiness.status_code != 200:
            raise RuntimeError("the local API is not ready")
        for _ in range(arguments.concurrency):
            warmup = await client.post("/v1/predict", json=PREDICTION_PAYLOAD)
            if warmup.status_code != 200:
                raise RuntimeError("a warm-up prediction failed")

        async def send_one() -> None:
            nonlocal failures
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.post("/v1/predict", json=PREDICTION_PAYLOAD)
                except httpx.HTTPError:
                    failures += 1
                else:
                    if response.status_code != 200:
                        failures += 1
                finally:
                    latencies_ms.append((time.perf_counter() - started) * 1_000.0)

        started = time.perf_counter()
        await asyncio.gather(*[send_one() for _ in range(arguments.requests)])
        elapsed = time.perf_counter() - started

    sorted_latencies = sorted(latencies_ms)
    p95_index = max(math.ceil(0.95 * len(sorted_latencies)) - 1, 0)
    return LoadResult(
        requests=arguments.requests,
        concurrency=arguments.concurrency,
        throughput_requests_per_second=arguments.requests / elapsed,
        error_rate=failures / arguments.requests,
        p95_latency_ms=sorted_latencies[p95_index],
    )


def main() -> int:
    arguments = _parser().parse_args()
    try:
        _validate_arguments(arguments)
        result = asyncio.run(_measure(arguments))
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 2

    passed = (
        result.throughput_requests_per_second >= arguments.min_throughput
        and result.error_rate <= arguments.max_error_rate
        and result.p95_latency_ms <= arguments.max_p95_ms
    )
    output: dict[str, Any] = {
        "status": "passed" if passed else "failed",
        "requests": result.requests,
        "concurrency": result.concurrency,
        "throughput_requests_per_second": round(result.throughput_requests_per_second, 2),
        "error_rate": round(result.error_rate, 6),
        "p95_latency_ms": round(result.p95_latency_ms, 2),
        "targets": {
            "min_throughput_requests_per_second": arguments.min_throughput,
            "max_error_rate": arguments.max_error_rate,
            "max_p95_latency_ms": arguments.max_p95_ms,
        },
    }
    print(json.dumps(output, allow_nan=False, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
