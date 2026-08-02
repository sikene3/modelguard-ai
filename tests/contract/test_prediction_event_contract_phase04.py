"""Frozen compatibility and Firehose-format contracts for prediction event v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from modelguard.api.schemas import PredictionRequest
from modelguard.data.schema import FEATURE_ORDER
from modelguard.inference.events import (
    FIREHOSE_OUTPUT_COMPRESSION,
    FIREHOSE_UTC_ARRIVAL_PREFIX,
    PREDICTION_EVENT_SCHEMA_VERSION,
    ApprovedSyntheticFeaturesV1,
    PredictionEventV1,
)

EVENT_FIELDS = {
    "event_schema_version",
    "event_id",
    "request_id",
    "event_timestamp",
    "model_version",
    "bundle_manifest_sha256",
    "input_schema_version",
    "features",
    "score",
    "decision",
    "latency_ms",
}
FEATURE_FIELDS = {
    "amount",
    "transaction_hour",
    "velocity_1h",
    "distance_from_home_km",
    "device_risk_score",
    "merchant_risk_score",
    "is_new_device",
    "country_code",
    "device_type",
}


def test_frozen_v1_example_validates_and_round_trips_canonically(repository_root: Path) -> None:
    fixture_path = repository_root / "tests/fixtures/contracts/prediction-event-v1.json"
    event = PredictionEventV1.model_validate_json(fixture_path.read_bytes())
    round_tripped = json.loads(event.model_dump_json())

    assert event.event_schema_version == PREDICTION_EVENT_SCHEMA_VERSION
    assert set(round_tripped) == EVENT_FIELDS
    assert set(round_tripped["features"]) == FEATURE_FIELDS
    assert round_tripped["event_timestamp"].endswith("Z")
    assert round_tripped["bundle_manifest_sha256"] == "a" * 64


def test_committed_json_schema_matches_the_runtime_contract(repository_root: Path) -> None:
    schema_path = repository_root / "contracts/prediction-event-v1.schema.json"
    committed: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
    generated = PredictionEventV1.model_json_schema()

    assert committed["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert committed["additionalProperties"] is False
    assert set(committed["properties"]) == EVENT_FIELDS
    assert set(committed["required"]) == EVENT_FIELDS
    assert committed["properties"]["event_schema_version"]["const"] == (
        PREDICTION_EVENT_SCHEMA_VERSION
    )
    assert committed["properties"]["event_timestamp"]["pattern"] == "Z$"
    assert committed["properties"]["features"]["additionalProperties"] is False
    assert set(committed["properties"]["features"]["properties"]) == FEATURE_FIELDS
    assert set(committed["properties"]["features"]["required"]) == FEATURE_FIELDS

    assert generated["additionalProperties"] is False
    assert set(generated["properties"]) == EVENT_FIELDS
    assert set(generated["required"]) == EVENT_FIELDS
    feature_reference = generated["properties"]["features"]["$ref"]
    feature_definition_name = feature_reference.rsplit("/", maxsplit=1)[-1]
    generated_features = generated["$defs"][feature_definition_name]
    assert generated_features["additionalProperties"] is False
    assert set(generated_features["properties"]) == FEATURE_FIELDS
    assert set(ApprovedSyntheticFeaturesV1.model_fields) == FEATURE_FIELDS
    assert list(ApprovedSyntheticFeaturesV1.model_fields) == list(FEATURE_ORDER)
    assert (
        ApprovedSyntheticFeaturesV1.model_json_schema()["properties"]
        == (PredictionRequest.model_json_schema()["properties"])
    )


def test_v1_rejects_unknown_or_sensitive_fields(repository_root: Path) -> None:
    fixture_path = repository_root / "tests/fixtures/contracts/prediction-event-v1.json"
    payload: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))

    with pytest.raises(ValidationError, match="extra_forbidden"):
        PredictionEventV1.model_validate({**payload, "email": "forbidden@example.invalid"})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PredictionEventV1.model_validate(
            {**payload, "features": {**payload["features"], "card_number": "forbidden"}}
        )

    missing_version = {
        key: value for key, value in payload.items() if key != "event_schema_version"
    }
    with pytest.raises(ValidationError, match="event_schema_version"):
        PredictionEventV1.model_validate_json(json.dumps(missing_version))

    noncanonical_utc = {**payload, "event_timestamp": "2026-08-02T12:34:56.789+00:00"}
    with pytest.raises(ValidationError, match="must end with Z"):
        PredictionEventV1.model_validate_json(json.dumps(noncanonical_utc))


def test_firehose_physical_contract_is_gzip_arrival_hour_jsonl_with_payload_identity() -> None:
    assert FIREHOSE_OUTPUT_COMPRESSION == "GZIP"
    assert FIREHOSE_UTC_ARRIVAL_PREFIX == (
        "predictions/year=!{timestamp:yyyy}/month=!{timestamp:MM}/"
        "day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    )
    assert "model_version" not in FIREHOSE_UTC_ARRIVAL_PREFIX
    assert "manifest" not in FIREHOSE_UTC_ARRIVAL_PREFIX
    assert {"model_version", "bundle_manifest_sha256", "input_schema_version"} <= EVENT_FIELDS
