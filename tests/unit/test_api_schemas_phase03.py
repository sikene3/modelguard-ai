"""Unit tests for the strict Pydantic v2 inference contracts."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from modelguard.api.schemas import PredictionRequest, PredictionResponse
from modelguard.data.schema import FEATURE_ORDER, canonical_feature_definitions
from modelguard.inference.predictor import RiskDecision


def test_prediction_request_matches_locked_feature_order(
    valid_prediction_payload: dict[str, object],
) -> None:
    request = PredictionRequest.model_validate(valid_prediction_payload)

    assert tuple(request.feature_values()) == FEATURE_ORDER
    assert PredictionRequest.model_json_schema()["additionalProperties"] is False


def test_prediction_request_json_schema_matches_frozen_bundle_schema() -> None:
    api_schema = PredictionRequest.model_json_schema()
    properties = api_schema["properties"]
    type_names = {
        "float": "number",
        "integer": "integer",
        "boolean": "boolean",
        "string": "string",
    }

    assert api_schema["required"] == list(FEATURE_ORDER)
    for definition in canonical_feature_definitions():
        property_schema = properties[definition.name]
        assert property_schema["type"] == type_names[definition.data_type]
        if definition.data_type in {"float", "integer"}:
            assert property_schema["minimum"] == definition.minimum
            assert property_schema["maximum"] == definition.maximum
        elif definition.data_type == "string":
            assert property_schema["enum"] == definition.categories


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("amount", 0.0),
        ("transaction_hour", 24),
        ("transaction_hour", 2.0),
        ("velocity_1h", -1),
        ("distance_from_home_km", math.inf),
        ("device_risk_score", math.nan),
        ("merchant_risk_score", 1.01),
        ("is_new_device", 1),
        ("country_code", "FR"),
        ("device_type", "phone"),
        ("amount", "4200.0"),
        ("country_code", None),
    ],
)
def test_prediction_request_rejects_invalid_nonfinite_and_coerced_values(
    field: str,
    invalid_value: Any,
    valid_prediction_payload: dict[str, object],
) -> None:
    changed = {**valid_prediction_payload, field: invalid_value}

    with pytest.raises(ValidationError):
        PredictionRequest.model_validate(changed)


def test_prediction_request_rejects_extra_fields(
    valid_prediction_payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PredictionRequest.model_validate({**valid_prediction_payload, "account_id": "sensitive"})


def test_prediction_response_is_finite_typed_and_versioned() -> None:
    response = PredictionResponse(
        request_id=UUID("00000000-0000-4000-8000-000000000001"),
        risk_score=0.75,
        decision=RiskDecision.HIGH_RISK,
        model_version="1.0.0",
        latency_ms=1.25,
    )

    assert response.model_dump(mode="json") == {
        "request_id": "00000000-0000-4000-8000-000000000001",
        "risk_score": 0.75,
        "decision": "high_risk",
        "model_version": "1.0.0",
        "latency_ms": 1.25,
    }
    with pytest.raises(ValidationError):
        PredictionResponse(
            request_id=UUID("00000000-0000-4000-8000-000000000001"),
            risk_score=math.nan,
            decision=RiskDecision.HIGH_RISK,
            model_version="unversioned",
            latency_ms=-1.0,
        )
