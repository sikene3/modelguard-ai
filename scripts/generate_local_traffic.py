#!/usr/bin/env python3
"""Send deterministic baseline or shifted synthetic traffic to a local ModelGuard API."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from modelguard.data.generator import generate_synthetic_data

DEFAULT_ROW_COUNTS = {"baseline": 1_000, "drifted": 1_000, "tiny": 25}
DEFAULT_SEEDS = {"baseline": 8_080, "drifted": 8_081, "tiny": 8_082}
RESPONSE_FIELDS = {"request_id", "risk_score", "decision", "model_version", "latency_ms"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=tuple(DEFAULT_ROW_COUNTS), required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--row-count", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--evidence", type=Path)
    return parser


def validate_local_url(value: str) -> str:
    """Accept only an origin-style loopback HTTP URL."""

    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("traffic generation accepts only a loopback HTTP origin URL")
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("traffic URL has an invalid port") from error
    return value.rstrip("/")


def _python_features(row: object) -> dict[str, Any]:
    values = row._asdict()  # type: ignore[attr-defined]
    return {
        "amount": float(values["amount"]),
        "transaction_hour": int(values["transaction_hour"]),
        "velocity_1h": int(values["velocity_1h"]),
        "distance_from_home_km": float(values["distance_from_home_km"]),
        "device_risk_score": float(values["device_risk_score"]),
        "merchant_risk_score": float(values["merchant_risk_score"]),
        "is_new_device": bool(values["is_new_device"]),
        "country_code": str(values["country_code"]),
        "device_type": str(values["device_type"]),
    }


def shift_features(features: dict[str, Any]) -> dict[str, Any]:
    """Apply a deterministic, bounded shift strong enough to exercise degraded drift."""

    shifted = dict(features)
    shifted.update(
        {
            "amount": min(25_000.0, float(features["amount"]) * 20.0 + 5_000.0),
            "velocity_1h": min(30, int(features["velocity_1h"]) + 15),
            "distance_from_home_km": min(
                1_000.0,
                float(features["distance_from_home_km"]) + 400.0,
            ),
            "device_risk_score": min(
                1.0,
                0.8 + 0.2 * float(features["device_risk_score"]),
            ),
            "merchant_risk_score": min(
                1.0,
                0.8 + 0.2 * float(features["merchant_risk_score"]),
            ),
            "is_new_device": True,
            "country_code": "BR",
            "device_type": "tablet",
        }
    )
    return shifted


def build_payloads(*, scenario: str, row_count: int, seed: int) -> list[dict[str, Any]]:
    """Create the exact schema payloads used by the local traffic scenarios."""

    if scenario not in DEFAULT_ROW_COUNTS:
        raise ValueError("unsupported traffic scenario")
    if row_count <= 0:
        raise ValueError("row-count must be positive")
    dataset = generate_synthetic_data(row_count, seed=seed)
    payloads = [_python_features(row) for row in dataset.itertuples(index=False)]
    if scenario == "drifted":
        return [shift_features(payload) for payload in payloads]
    return payloads


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise OSError("evidence path must be a regular non-symlink file")
    payload = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _validate_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict) or set(payload) != RESPONSE_FIELDS:
        raise ValueError("prediction response fields did not match the v1 contract")
    UUID(str(payload["request_id"]))
    score = float(payload["risk_score"])
    latency = float(payload["latency_ms"])
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("prediction score was not finite in [0,1]")
    if not math.isfinite(latency) or latency < 0.0:
        raise ValueError("prediction latency was not finite and non-negative")
    if payload["decision"] not in {"low_risk", "high_risk"}:
        raise ValueError("prediction decision was invalid")
    if not isinstance(payload["model_version"], str):
        raise ValueError("prediction model version was invalid")
    return payload


async def send_traffic(
    *,
    url: str,
    payloads: list[dict[str, object]],
    concurrency: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Send bounded concurrent requests and return machine-readable aggregate evidence."""

    if concurrency < 1 or concurrency > 64:
        raise ValueError("concurrency must be in [1,64]")
    if timeout_seconds <= 0.0 or timeout_seconds > 120.0:
        raise ValueError("timeout-seconds must be in (0,120]")
    semaphore = asyncio.Semaphore(min(concurrency, len(payloads)))
    decisions: Counter[str] = Counter()
    model_versions: Counter[str] = Counter()
    request_ids: set[UUID] = set()
    scores: list[float] = []
    failures: Counter[str] = Counter()
    latency_ms: list[float] = []
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(timeout_seconds)

    async with httpx.AsyncClient(base_url=url, timeout=timeout, limits=limits) as client:
        readiness = await client.get("/health/ready")
        if readiness.status_code != 200 or readiness.json() != {"status": "ready"}:
            raise RuntimeError("the local API was not ready")

        async def send_one(payload: dict[str, object]) -> None:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.post("/v1/predict", json=payload)
                    result = _validate_response(response)
                    request_id = UUID(str(result["request_id"]))
                    if request_id in request_ids:
                        raise ValueError("the API returned a duplicate request ID")
                    request_ids.add(request_id)
                    decisions[str(result["decision"])] += 1
                    model_versions[str(result["model_version"])] += 1
                    scores.append(float(result["risk_score"]))
                except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as error:
                    failures[type(error).__name__] += 1
                finally:
                    latency_ms.append((time.perf_counter() - started) * 1_000.0)

        await asyncio.gather(*(send_one(payload) for payload in payloads))

    successes = len(scores)
    return {
        "requests": len(payloads),
        "successes": successes,
        "failures": len(payloads) - successes,
        "failure_categories": dict(sorted(failures.items())),
        "decision_counts": dict(sorted(decisions.items())),
        "model_versions": dict(sorted(model_versions.items())),
        "score": {
            "minimum": min(scores) if scores else None,
            "maximum": max(scores) if scores else None,
            "mean": sum(scores) / len(scores) if scores else None,
        },
        "client_latency_ms": {
            "maximum": max(latency_ms) if latency_ms else None,
            "mean": sum(latency_ms) / len(latency_ms) if latency_ms else None,
        },
    }


def main() -> int:
    arguments = _parser().parse_args()
    started_at = _utc_now()
    try:
        url = validate_local_url(arguments.url)
        row_count = (
            arguments.row_count
            if arguments.row_count is not None
            else DEFAULT_ROW_COUNTS[arguments.scenario]
        )
        seed = arguments.seed if arguments.seed is not None else DEFAULT_SEEDS[arguments.scenario]
        payloads = build_payloads(
            scenario=arguments.scenario,
            row_count=row_count,
            seed=seed,
        )
        measured = asyncio.run(
            send_traffic(
                url=url,
                payloads=payloads,
                concurrency=arguments.concurrency,
                timeout_seconds=arguments.timeout_seconds,
            )
        )
        passed = measured["failures"] == 0 and measured["successes"] == row_count
        result: dict[str, Any] = {
            "schema_version": "modelguard.local-traffic-evidence.v1",
            "status": "passed" if passed else "failed",
            "scenario": arguments.scenario,
            "seed": seed,
            "concurrency": arguments.concurrency,
            "url": url,
            "started_at": started_at,
            "completed_at": _utc_now(),
            **measured,
        }
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
        result = {
            "schema_version": "modelguard.local-traffic-evidence.v1",
            "status": "failed",
            "scenario": arguments.scenario,
            "started_at": started_at,
            "completed_at": _utc_now(),
            "reason": str(error),
        }
        passed = False

    if arguments.evidence is not None:
        try:
            _atomic_json_write(arguments.evidence, result)
        except OSError as error:
            print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
            return 2
    print(json.dumps(result, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
