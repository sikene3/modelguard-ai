"""Unit tests for Prometheus, bounded EMF, and structured log redaction."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from modelguard.core.config import ApiAccessMode, AppEnvironment, LogLevel, Settings
from modelguard.core.logging import REDACTED, configure_json_logging
from modelguard.core.telemetry import EmfTelemetry, ErrorKind, PrometheusTelemetry, build_telemetry


def test_prometheus_exposes_required_low_cardinality_signals() -> None:
    telemetry = PrometheusTelemetry()
    telemetry.record_model_load("success", 0.05)
    telemetry.record_http_request(
        method="POST",
        route="/v1/predict",
        status_code=200,
        latency_seconds=0.01,
    )
    telemetry.record_prediction("high_risk")
    telemetry.record_event_sink("timeout", 0.1)
    telemetry.record_error(ErrorKind.EVENT_SINK)

    metrics = telemetry.render_prometheus().decode("utf-8")

    assert (
        'modelguard_api_requests_total{method="POST",route="/v1/predict",status_class="2xx"}'
        in metrics
    )
    assert "modelguard_api_request_latency_seconds_bucket" in metrics
    assert 'modelguard_predictions_total{decision="high_risk"}' in metrics
    assert 'modelguard_model_load_total{outcome="success"}' in metrics
    assert 'modelguard_event_sink_operations_total{outcome="timeout"}' in metrics
    assert 'modelguard_errors_total{kind="event_sink"}' in metrics


def test_emf_uses_only_fixed_bounded_dimensions_and_metric_names() -> None:
    lines: list[str] = []
    telemetry = EmfTelemetry(
        environment=AppEnvironment.AWS,
        access_mode=ApiAccessMode.HTTPS_BEARER,
        writer=lines.append,
        epoch_milliseconds=lambda: 1_786_000_000_000,
    )

    telemetry.record_model_load("success", 0.05)
    telemetry.record_http_request(
        method="POST",
        route="/v1/predict",
        status_code=200,
        latency_seconds=0.01,
    )
    telemetry.record_prediction("low_risk")
    telemetry.record_event_sink("success", 0.001)
    telemetry.record_error(ErrorKind.AUTH)

    assert len(lines) == 5
    for line in lines:
        payload: dict[str, Any] = json.loads(line)
        metadata = payload["_aws"]["CloudWatchMetrics"][0]
        assert metadata["Namespace"] == "ModelGuardAI"
        assert metadata["Dimensions"] == [["Service", "Environment", "AccessMode"]]
        assert payload["Service"] == "api"
        assert payload["Environment"] == "aws"
        assert payload["AccessMode"] == "https_token"
        dimension_names = {name for group in metadata["Dimensions"] for name in group}
        assert dimension_names.isdisjoint(
            {"RequestId", "EventId", "Token", "Feature", "ModelVersion"}
        )


def test_aws_factory_adds_emf_while_local_factory_does_not() -> None:
    aws_lines: list[str] = []
    aws_settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
        alb_allowed_cidr="203.0.113.8/32",
    )
    aws_telemetry = build_telemetry(aws_settings, emf_writer=aws_lines.append)
    aws_telemetry.record_error(ErrorKind.VALIDATION)
    assert len(aws_lines) == 1

    local_lines: list[str] = []
    local_telemetry = build_telemetry(
        Settings(_env_file=None),
        emf_writer=local_lines.append,
    )
    local_telemetry.record_error(ErrorKind.VALIDATION)
    assert local_lines == []


def test_json_logger_redacts_sensitive_keys_and_configured_values() -> None:
    stream = io.StringIO()
    secret = "super-secret-bearer-value-that-must-not-leak"
    logger = configure_json_logging(
        LogLevel.INFO,
        stream=stream,
        sensitive_values=(secret,),
    )

    logger.info(
        "redaction_probe",
        request_id="00000000-0000-4000-8000-000000000001",
        authorization=f"Bearer {secret}",
        note=f"accidental value: {secret}",
        binary_note=f"binary value: {secret}".encode(),
        diagnostic_path=Path("/tmp") / secret / "probe",
        request_body={"amount": 4200.0},
        latency_ms=1.25,
    )

    raw_line = stream.getvalue().strip()
    payload = json.loads(raw_line)
    assert secret not in raw_line
    assert payload["authorization"] == REDACTED
    assert payload["request_body"] == REDACTED
    assert REDACTED in payload["note"]
    assert REDACTED in payload["binary_note"]
    assert REDACTED in payload["diagnostic_path"]
    assert payload["request_id"] == "00000000-0000-4000-8000-000000000001"
    assert payload["latency_ms"] == 1.25
