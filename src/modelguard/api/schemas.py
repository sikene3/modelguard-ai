"""Strict Pydantic v2 HTTP request and response contracts."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from modelguard.inference.predictor import RiskDecision


class StrictApiModel(BaseModel):
    """Reject extra keys, coercion surprises, and non-finite JSON values."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class PredictionRequest(StrictApiModel):
    """Frozen Phase 02 feature contract exposed over HTTP."""

    amount: Annotated[float, Field(ge=0.01, le=25_000.0)]
    transaction_hour: Annotated[StrictInt, Field(ge=0, le=23)]
    velocity_1h: Annotated[StrictInt, Field(ge=0, le=30)]
    distance_from_home_km: Annotated[float, Field(ge=0.0, le=1_000.0)]
    device_risk_score: Annotated[float, Field(ge=0.0, le=1.0)]
    merchant_risk_score: Annotated[float, Field(ge=0.0, le=1.0)]
    is_new_device: StrictBool
    country_code: Literal["BR", "DE", "EG", "GB", "IN", "US"]
    device_type: Literal["desktop", "mobile", "tablet"]

    def feature_values(self) -> dict[str, object]:
        """Return values in declaration/canonical model order."""

        return dict(self.model_dump(mode="python"))


class PredictionResponse(StrictApiModel):
    """Successful versioned inference result."""

    request_id: UUID
    risk_score: Annotated[float, Field(ge=0.0, le=1.0)]
    decision: RiskDecision
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    latency_ms: Annotated[float, Field(ge=0.0)]


class LiveResponse(StrictApiModel):
    status: Literal["live"] = "live"


class ReadyResponse(StrictApiModel):
    status: Literal["ready"] = "ready"


class NotReadyResponse(StrictApiModel):
    status: Literal["not_ready"] = "not_ready"


class VersionResponse(StrictApiModel):
    service_version: str
    model_ready: bool
    model_version: str | None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ErrorResponse(StrictApiModel):
    code: str
    message: str
    request_id: UUID
