"""Versioned, fully explicit Phase 02 training configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from modelguard.core.hashing import HashRecord, canonical_json_hash
from modelguard.core.serialization import StrictArtifactModel, load_json_model
from modelguard.data.schema import COUNTRY_CODES, DEVICE_TYPES, FEATURE_ORDER


class DatasetConfig(StrictArtifactModel):
    generator_version: Literal["modelguard.synthetic-independent.v1"]
    row_count: int = Field(ge=100)
    seed: int


class SplitConfig(StrictArtifactModel):
    strategy: Literal["canonical_stratified_train_validation_test"]
    train_fraction: float = Field(gt=0.0, lt=1.0)
    validation_fraction: float = Field(gt=0.0, lt=1.0)
    test_fraction: float = Field(gt=0.0, lt=1.0)
    train_remainder_seed: int
    validation_test_seed: int

    @model_validator(mode="after")
    def validate_fractions(self) -> SplitConfig:
        total = self.train_fraction + self.validation_fraction + self.test_fraction
        if abs(total - 1.0) > 1e-12:
            raise ValueError("split fractions must sum exactly to one within 1e-12")
        return self


class ImputerConfig(StrictArtifactModel):
    missing_values: Literal["nan"]
    strategy: Literal["median", "constant"]
    fill_value: str | None
    copy_parameter: Literal[True] = Field(alias="copy")
    add_indicator: Literal[False]
    keep_empty_features: Literal[False]


class StandardScalerConfig(StrictArtifactModel):
    copy_parameter: Literal[True] = Field(alias="copy")
    with_mean: Literal[True]
    with_std: Literal[True]


class OneHotEncoderConfig(StrictArtifactModel):
    categories: list[list[str]]
    drop: None
    sparse_output: Literal[True]
    dtype: Literal["float64"]
    handle_unknown: Literal["ignore"]
    min_frequency: None
    max_categories: None
    feature_name_combiner: Literal["concat"]

    @model_validator(mode="after")
    def validate_categories(self) -> OneHotEncoderConfig:
        expected = [
            [*list(COUNTRY_CODES), "__MISSING__"],
            [*list(DEVICE_TYPES), "__MISSING__"],
        ]
        if self.categories != expected:
            raise ValueError("one-hot categories must match the locked categorical universe")
        return self


class ColumnTransformerConfig(StrictArtifactModel):
    remainder: Literal["drop"]
    sparse_threshold: float = Field(ge=0.0, le=1.0)
    n_jobs: None
    transformer_weights: None
    verbose: Literal[False]
    verbose_feature_names_out: Literal[True]


class PipelineConfig(StrictArtifactModel):
    transform_input: None
    memory: None
    verbose: Literal[False]


class PreprocessingConfig(StrictArtifactModel):
    numeric_imputer: ImputerConfig
    numeric_scaler: StandardScalerConfig
    categorical_imputer: ImputerConfig
    one_hot_encoder: OneHotEncoderConfig
    column_transformer: ColumnTransformerConfig
    pipeline: PipelineConfig

    @model_validator(mode="after")
    def validate_imputers(self) -> PreprocessingConfig:
        if self.numeric_imputer.strategy != "median" or self.numeric_imputer.fill_value is not None:
            raise ValueError("numeric imputation must use median with no fill value")
        if (
            self.categorical_imputer.strategy != "constant"
            or self.categorical_imputer.fill_value != "__MISSING__"
        ):
            raise ValueError("categorical imputation must use the __MISSING__ bucket")
        return self


class LogisticRegressionConfig(StrictArtifactModel):
    penalty: Literal["deprecated"]
    C: float = Field(gt=0.0)
    l1_ratio: float = Field(ge=0.0, le=1.0)
    dual: Literal[False]
    tol: float = Field(gt=0.0)
    fit_intercept: Literal[True]
    intercept_scaling: float = Field(gt=0.0)
    class_weight: None
    random_state: int
    solver: Literal["lbfgs"]
    max_iter: int = Field(gt=0)
    verbose: Literal[0]
    warm_start: Literal[False]
    n_jobs: None


class CalibrationConfig(StrictArtifactModel):
    n_splits: Literal[5]
    shuffle: Literal[True]
    random_state: int
    method: Literal["sigmoid"]
    ensemble: Literal[True]
    n_jobs: None


class ThresholdConfig(StrictArtifactModel):
    comparison: Literal["score >= threshold"]
    grid_denominator: Literal[1000]
    false_negative_cost: Literal[10]
    false_positive_cost: Literal[1]
    tie_policy: Literal["cost_then_fewer_fn_then_fewer_fp_then_lowest_threshold"]


class BaselineConfig(StrictArtifactModel):
    numeric_quantiles: list[float]
    numeric_quantile_method: Literal["linear"]
    score_edges: list[float]
    other_bucket: Literal["__OTHER__"]
    missing_bucket: Literal["__MISSING__"]

    @model_validator(mode="after")
    def validate_bins(self) -> BaselineConfig:
        expected = [index / 10 for index in range(11)]
        if self.numeric_quantiles != expected or self.score_edges != expected:
            raise ValueError("baseline numeric quantiles and score edges must be fixed deciles")
        return self


class MlflowConfig(StrictArtifactModel):
    tracking_scheme: Literal["file"]
    tracking_subdirectory: Literal["mlruns"]
    experiment_name: str = Field(min_length=1)
    autolog: Literal[False]


class TrainingConfig(StrictArtifactModel):
    """Complete versioned behavior for generation, fitting, calibration, and evaluation."""

    contract_version: Literal["modelguard.training-config.v1"]
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    feature_allowlist: list[str]
    dataset: DatasetConfig
    split: SplitConfig
    preprocessing: PreprocessingConfig
    logistic_regression: LogisticRegressionConfig
    calibration: CalibrationConfig
    threshold: ThresholdConfig
    baseline: BaselineConfig
    mlflow: MlflowConfig

    @model_validator(mode="after")
    def validate_locked_contract(self) -> TrainingConfig:
        if self.feature_allowlist != list(FEATURE_ORDER):
            raise ValueError("feature_allowlist must exactly match the ordered input contract")
        return self


class ConfigManifest(StrictArtifactModel):
    """Canonical configuration identity plus the exact validated parameters."""

    contract_version: Literal["modelguard.config-manifest.v1"] = "modelguard.config-manifest.v1"
    created_at: str
    configuration_hash: HashRecord
    configuration: TrainingConfig


def load_training_config(path: Path) -> TrainingConfig:
    """Load a strict versioned training configuration."""

    return load_json_model(path, TrainingConfig)


def training_config_hash(config: TrainingConfig) -> HashRecord:
    """Hash configuration semantics independent of source JSON formatting."""

    return canonical_json_hash(
        config.model_dump(mode="json", by_alias=True),
        ordering="JSON object keys ascending; configured list order preserved",
        exclusions=["source JSON whitespace", "source JSON key order", "artifact timestamps"],
    )
