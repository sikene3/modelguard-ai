"""Versioned deterministic monitoring policy and its canonical identity."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from modelguard.core.hashing import HashRecord, canonical_json_hash
from modelguard.core.serialization import StrictArtifactModel, load_json_model
from modelguard.data.schema import CATEGORICAL_FEATURES, NUMERIC_FEATURES

MONITORING_CONFIG_VERSION: Literal["modelguard.monitoring-config.v1"] = (
    "modelguard.monitoring-config.v1"
)
LABEL_SCHEMA_VERSION: Literal["modelguard.label.v1"] = "modelguard.label.v1"
PERFORMANCE_SCOPE_WORDING: Literal[
    "synthetic-policy cost on the labeled subset versus held-out synthetic reference"
] = "synthetic-policy cost on the labeled subset versus held-out synthetic reference"
AWS_LOCKED_MONITORING_POLICY_SHA256 = (
    "edd3177bc4a692262858b6ec2e60a991cdce1bc844ef7eb0becac6846df56c73"
)


class MonitoringConfig(StrictArtifactModel):
    """Every value that can change monitoring results or state."""

    contract_version: Literal["modelguard.monitoring-config.v1"] = MONITORING_CONFIG_VERSION
    window_seconds: int = Field(default=3_600, gt=0)
    finalization_grace_seconds: int = Field(default=600, ge=0)
    stale_after_seconds: int = Field(default=7_200, gt=0)
    minimum_accepted_events: int = Field(default=500, ge=1)
    smoothing_epsilon: float = Field(default=1e-6, gt=0.0, lt=1.0)
    psi_warning_threshold: float = Field(default=0.10, ge=0.0)
    psi_degraded_threshold: float = Field(default=0.25, ge=0.0)
    js_warning_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    js_degraded_threshold: float = Field(default=0.20, ge=0.0, le=1.0)
    missingness_warning_threshold: float = Field(default=0.02, ge=0.0, le=1.0)
    missingness_invalid_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    rejected_fraction_invalid_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    label_schema_version: Literal["modelguard.label.v1"] = LABEL_SCHEMA_VERSION
    minimum_label_coverage: float = Field(default=0.80, ge=0.0, le=1.0)
    minimum_labeled_rows: int = Field(default=500, ge=1)
    minimum_positive_labels: int = Field(default=20, ge=1)
    minimum_negative_labels: int = Field(default=100, ge=1)
    false_negative_cost: Literal[10] = 10
    false_positive_cost: Literal[1] = 1
    performance_warning_delta: float = Field(default=0.10, ge=0.0)
    performance_degraded_delta: float = Field(default=0.25, ge=0.0)
    required_numeric_features: list[str] = Field(default_factory=lambda: list(NUMERIC_FEATURES))
    required_categorical_features: list[str] = Field(
        default_factory=lambda: list(CATEGORICAL_FEATURES)
    )
    other_bucket: Literal["__OTHER__"] = "__OTHER__"
    missing_bucket: Literal["__MISSING__"] = "__MISSING__"
    performance_scope_wording: Literal[
        "synthetic-policy cost on the labeled subset versus held-out synthetic reference"
    ] = PERFORMANCE_SCOPE_WORDING

    @model_validator(mode="after")
    def validate_policy_ordering(self) -> MonitoringConfig:
        if self.psi_warning_threshold >= self.psi_degraded_threshold:
            raise ValueError("PSI warning must be below degraded")
        if self.js_warning_threshold >= self.js_degraded_threshold:
            raise ValueError("JS warning must be below degraded")
        if self.missingness_warning_threshold >= self.missingness_invalid_threshold:
            raise ValueError("missingness warning must be below invalid")
        if self.performance_warning_delta >= self.performance_degraded_delta:
            raise ValueError("performance warning must be below degraded")
        if self.required_numeric_features != list(NUMERIC_FEATURES):
            raise ValueError("required numeric features must match the frozen model contract")
        if self.required_categorical_features != list(CATEGORICAL_FEATURES):
            raise ValueError("required categorical features must match the frozen model contract")
        return self


def monitoring_config_hash(config: MonitoringConfig) -> HashRecord:
    """Hash result-affecting policy once, independent of source formatting."""

    return canonical_json_hash(
        config.model_dump(mode="json"),
        ordering="JSON object keys ascending; required feature order preserved",
        exclusions=["source JSON whitespace", "source JSON key order", "run timestamps"],
    )


def load_monitoring_config(path: Path) -> MonitoringConfig:
    """Load one strict versioned monitoring policy without environment-dependent defaults."""

    return load_json_model(path, MonitoringConfig)
