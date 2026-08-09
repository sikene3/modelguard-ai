"""API integration tests for local persistence and Firehose producer outcomes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from botocore.exceptions import ClientError

from modelguard.api.main import create_app
from modelguard.core.config import ApiAccessMode, AppEnvironment, EventSink, Settings
from modelguard.core.telemetry import build_telemetry
from modelguard.inference.events import PredictionEventV1, freeze_local_event_snapshot
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


class FakeFirehoseClient:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.records: list[bytes] = []

    def put_record(
        self,
        *,
        DeliveryStreamName: str,
        Record: Mapping[str, bytes],
    ) -> Mapping[str, Any]:
        assert DeliveryStreamName == "modelguard-demo-predictions"
        self.records.append(Record["Data"])
        if self.fail:
            raise ClientError(
                {
                    "Error": {"Code": "AccessDeniedException", "Message": "fake"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "PutRecord",
            )
        return {"RecordId": f"accepted-{len(self.records)}"}

    def close(self) -> None:
        return None


def test_local_api_writes_one_parseable_event_per_successful_prediction(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
    tmp_path: Path,
) -> None:
    event_directory = tmp_path / "predictions"
    settings = api_settings.model_copy(
        update={"event_sink": EventSink.LOCAL, "local_event_dir": event_directory}
    )
    logger = RecordingLogger()
    telemetry = build_telemetry(settings)

    async def exercise() -> tuple[list[dict[str, Any]], str]:
        app = create_app(settings, telemetry=telemetry, logger=logger)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                responses = [
                    await client.post("/v1/predict", json=valid_prediction_payload)
                    for _ in range(3)
                ]
                metrics = (await client.get("/metrics")).text
                assert freeze_local_event_snapshot(event_directory).closed_files == ()
        return [response.json() for response in responses], metrics

    response_payloads, metrics = asyncio.run(exercise())

    assert all(
        set(payload) == {"request_id", "risk_score", "decision", "model_version", "latency_ms"}
        for payload in response_payloads
    )
    snapshot = freeze_local_event_snapshot(event_directory)
    assert len(snapshot.closed_files) == 1
    closed_file = snapshot.closed_files[0]
    assert list(event_directory.glob("*.open")) == []
    lines = closed_file.read_bytes().splitlines(keepends=True)
    assert len(lines) == 3
    assert all(line.endswith(b"\n") and line.count(b"\n") == 1 for line in lines)

    events = [PredictionEventV1.model_validate_json(line) for line in lines]
    assert len({event.event_id for event in events}) == 3
    assert len({event.request_id for event in events}) == 3
    responses_by_request = {UUID(payload["request_id"]): payload for payload in response_payloads}
    for event in events:
        response = responses_by_request[event.request_id]
        assert event.features.model_dump(mode="python") == valid_prediction_payload
        assert event.score == response["risk_score"]
        assert event.decision.value == response["decision"]
        assert event.model_version == response["model_version"] == "1.0.0"
        assert event.latency_ms == response["latency_ms"]
        assert event.input_schema_version == "modelguard.input.v1"
        assert len(event.bundle_manifest_sha256) == 64
        assert event.event_timestamp.utcoffset() is not None
        assert event.event_timestamp.utcoffset().total_seconds() == 0.0

    assert 'modelguard_event_sink_operations_total{outcome="local_persisted"} 3.0' in metrics
    assert sum(event == "prediction_event_local_persisted" for _, event, _ in logger.entries) == 3


def test_firehose_acceptance_and_failure_are_separate_fail_open_aws_signals(
    api_settings: Settings,
    valid_prediction_payload: dict[str, object],
) -> None:
    base_settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
        alb_allowed_cidr="203.0.113.8/32",
        event_sink=EventSink.AWS,
        firehose_stream_name="modelguard-demo-predictions",
        model_bundle_path=api_settings.model_bundle_path,
        active_model_version="1.0.0",
    )

    async def exercise(
        fail: bool,
    ) -> tuple[int, str, list[str], RecordingLogger, FakeFirehoseClient]:
        emf_lines: list[str] = []
        telemetry = build_telemetry(base_settings, emf_writer=emf_lines.append)
        logger = RecordingLogger()
        client = FakeFirehoseClient(fail=fail)
        app = create_app(
            base_settings,
            model_loader=VerifiedModelLoader(),
            telemetry=telemetry,
            logger=logger,
            firehose_client=client,
        )
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as http_client:
                response = await http_client.post(
                    "/v1/predict",
                    json=valid_prediction_payload,
                    headers={"x-forwarded-proto": "http"},
                )
        return (
            response.status_code,
            telemetry.render_prometheus().decode("utf-8"),
            emf_lines,
            logger,
            client,
        )

    accepted = asyncio.run(exercise(False))
    failed = asyncio.run(exercise(True))

    accepted_status, accepted_metrics, accepted_emf, accepted_logger, accepted_client = accepted
    assert accepted_status == 200
    assert len(accepted_client.records) == 1
    assert accepted_client.records[0].endswith(b"\n")
    PredictionEventV1.model_validate_json(accepted_client.records[0])
    assert 'modelguard_event_sink_operations_total{outcome="firehose_accepted"} 1.0' in (
        accepted_metrics
    )
    assert any("FirehoseProducerAccepted" in line for line in accepted_emf)
    assert any(
        event == "prediction_event_firehose_producer_accepted"
        for _, event, _ in accepted_logger.entries
    )

    failed_status, failed_metrics, failed_emf, failed_logger, failed_client = failed
    assert failed_status == 200
    assert len(failed_client.records) == 1
    assert (
        'modelguard_event_sink_operations_total{outcome="firehose_producer_failed"} 1.0'
        in failed_metrics
    )
    assert any("FirehoseProducerFailure" in line for line in failed_emf)
    assert any("EventSinkErrors" in line for line in failed_emf)
    assert any(
        event == "prediction_event_firehose_producer_failed"
        for _, event, _ in failed_logger.entries
    )

    producer_log_names = " ".join(
        event for _, event, _ in [*accepted_logger.entries, *failed_logger.entries]
    ).casefold()
    assert "delivered" not in producer_log_names
    assert "s3" not in producer_log_names
