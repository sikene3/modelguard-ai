"""Canonical synthetic-data and inference feature contracts."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, model_validator

from modelguard.core.hashing import HashRecord
from modelguard.core.serialization import StrictArtifactModel

ID_COLUMN = "event_id"
LABEL_COLUMN = "is_fraud"
FEATURE_ORDER = (
    "amount",
    "transaction_hour",
    "velocity_1h",
    "distance_from_home_km",
    "device_risk_score",
    "merchant_risk_score",
    "is_new_device",
    "country_code",
    "device_type",
)
NUMERIC_FEATURES = (
    "amount",
    "transaction_hour",
    "velocity_1h",
    "distance_from_home_km",
    "device_risk_score",
    "merchant_risk_score",
    "is_new_device",
)
CATEGORICAL_FEATURES = ("country_code", "device_type")
COUNTRY_CODES = ("BR", "DE", "EG", "GB", "IN", "US")
DEVICE_TYPES = ("desktop", "mobile", "tablet")
DATASET_COLUMNS = (ID_COLUMN, *FEATURE_ORDER, LABEL_COLUMN)
GENERATOR_ONLY_COLUMNS = frozenset(
    {
        "latent_probability",
        "latent_logit",
        "probability",
        "logit",
        "row_index",
        "generator_index",
    }
)


class FeatureDefinition(StrictArtifactModel):
    """One ordered request field and its closed input domain."""

    name: str
    data_type: Literal["float", "integer", "boolean", "string"]
    nullable: Literal[False] = False
    minimum: float | int | None = None
    maximum: float | int | None = None
    categories: list[str] | None = None

    @model_validator(mode="after")
    def validate_domain_shape(self) -> FeatureDefinition:
        if self.data_type in {"float", "integer"}:
            if self.minimum is None or self.maximum is None or self.categories is not None:
                raise ValueError("numeric features require finite bounds and no categories")
            if self.minimum > self.maximum:
                raise ValueError("feature minimum cannot exceed maximum")
        elif self.data_type == "string":
            if not self.categories or self.minimum is not None or self.maximum is not None:
                raise ValueError("string features require a non-empty categorical domain")
            if len(set(self.categories)) != len(self.categories):
                raise ValueError("feature categories must be unique")
        elif any(value is not None for value in (self.minimum, self.maximum, self.categories)):
            raise ValueError("boolean features do not accept numeric or categorical metadata")
        return self


def canonical_feature_definitions() -> list[FeatureDefinition]:
    """Return the locked Phase 02 request schema in model feature order."""

    return [
        FeatureDefinition(name="amount", data_type="float", minimum=0.01, maximum=25_000.0),
        FeatureDefinition(name="transaction_hour", data_type="integer", minimum=0, maximum=23),
        FeatureDefinition(name="velocity_1h", data_type="integer", minimum=0, maximum=30),
        FeatureDefinition(
            name="distance_from_home_km", data_type="float", minimum=0.0, maximum=1_000.0
        ),
        FeatureDefinition(name="device_risk_score", data_type="float", minimum=0.0, maximum=1.0),
        FeatureDefinition(name="merchant_risk_score", data_type="float", minimum=0.0, maximum=1.0),
        FeatureDefinition(name="is_new_device", data_type="boolean"),
        FeatureDefinition(name="country_code", data_type="string", categories=list(COUNTRY_CODES)),
        FeatureDefinition(name="device_type", data_type="string", categories=list(DEVICE_TYPES)),
    ]


class InputSchemaContract(StrictArtifactModel):
    """Strict, ordered feature schema consumed by later inference phases."""

    schema_version: Literal["modelguard.input.v1"] = "modelguard.input.v1"
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    strict: Literal[True] = True
    feature_order: list[str]
    features: list[FeatureDefinition]
    smoke_example: dict[str, Any]

    @model_validator(mode="after")
    def validate_canonical_schema(self) -> InputSchemaContract:
        if self.feature_order != list(FEATURE_ORDER):
            raise ValueError("feature_order does not match the locked allowlist")
        expected = [item.model_dump(mode="json") for item in canonical_feature_definitions()]
        actual = [item.model_dump(mode="json") for item in self.features]
        if actual != expected:
            raise ValueError("feature definitions do not match the locked Phase 02 schema")
        if set(self.smoke_example) != set(FEATURE_ORDER):
            raise ValueError("smoke_example must use the exact feature allowlist")
        for definition in self.features:
            value = self.smoke_example[definition.name]
            if value is None:
                raise ValueError(f"smoke_example.{definition.name} cannot be null")
            if definition.data_type == "boolean":
                if type(value) is not bool:
                    raise ValueError(f"smoke_example.{definition.name} must be a boolean")
                continue
            if definition.data_type == "integer":
                if type(value) is not int:
                    raise ValueError(f"smoke_example.{definition.name} must be an integer")
            elif definition.data_type == "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"smoke_example.{definition.name} must be numeric")
                if not math.isfinite(float(value)):
                    raise ValueError(f"smoke_example.{definition.name} must be finite")
            else:
                if not isinstance(value, str) or value not in (definition.categories or []):
                    raise ValueError(
                        f"smoke_example.{definition.name} must be in the categorical domain"
                    )
                continue
            minimum = definition.minimum
            maximum = definition.maximum
            if minimum is None or maximum is None:
                raise RuntimeError(
                    f"internal numeric schema is missing bounds for {definition.name}"
                )
            if not minimum <= value <= maximum:
                raise ValueError(f"smoke_example.{definition.name} is outside the schema bounds")
        return self


def build_input_schema(model_version: str) -> InputSchemaContract:
    """Create the canonical input schema and a schema-valid smoke row."""

    return InputSchemaContract(
        model_version=model_version,
        feature_order=list(FEATURE_ORDER),
        features=canonical_feature_definitions(),
        smoke_example={
            "amount": 4200.0,
            "transaction_hour": 2,
            "velocity_1h": 8,
            "distance_from_home_km": 180.0,
            "device_risk_score": 0.82,
            "merchant_risk_score": 0.64,
            "is_new_device": True,
            "country_code": "EG",
            "device_type": "mobile",
        },
    )


class DatasetManifest(StrictArtifactModel):
    """Identity and generation lineage for the persisted canonical dataset."""

    contract_version: Literal["modelguard.dataset-manifest.v1"] = "modelguard.dataset-manifest.v1"
    created_at: str
    generator_version: Literal["modelguard.synthetic-independent.v1"]
    generator_seed: int
    row_count: int = Field(gt=0)
    columns: list[str]
    id_column: Literal["event_id"] = "event_id"
    label_column: Literal["is_fraud"] = "is_fraud"
    class_counts: dict[str, int]
    dataset_hash: HashRecord


class QualityManifest(StrictArtifactModel):
    """Persisted evidence that the exact dataset passed every quality rule."""

    contract_version: Literal["modelguard.quality-manifest.v1"] = "modelguard.quality-manifest.v1"
    created_at: str
    passed: Literal[True] = True
    dataset_hash: HashRecord
    row_count: int = Field(gt=0)
    class_counts: dict[str, int]
    missing_counts: dict[str, int]
    checks: list[str]
