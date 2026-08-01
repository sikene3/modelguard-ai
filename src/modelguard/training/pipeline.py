"""Explicit sklearn pipeline, train-only calibration, and fit-boundary audit."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from pydantic import Field, model_validator
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from modelguard.core.hashing import HashRecord
from modelguard.core.serialization import StrictArtifactModel
from modelguard.data.schema import CATEGORICAL_FEATURES, FEATURE_ORDER, NUMERIC_FEATURES
from modelguard.data.split import membership_hash
from modelguard.training.config import TrainingConfig


class CalibrationFoldAudit(StrictArtifactModel):
    """Canonical membership evidence for one train-only calibration fold."""

    fold_index: int = Field(ge=0)
    estimator_fit_count: int = Field(gt=0)
    calibration_count: int = Field(gt=0)
    estimator_fit_membership_hash: HashRecord
    calibration_membership_hash: HashRecord
    estimator_fit_class_counts: dict[str, int]
    calibration_class_counts: dict[str, int]

    @model_validator(mode="after")
    def validate_support(self) -> CalibrationFoldAudit:
        for name, counts, expected_count in (
            ("estimator fit", self.estimator_fit_class_counts, self.estimator_fit_count),
            ("calibration", self.calibration_class_counts, self.calibration_count),
        ):
            if set(counts) != {"0", "1"} or any(count <= 0 for count in counts.values()):
                raise ValueError(f"{name} fold partition must contain both binary classes")
            if sum(counts.values()) != expected_count:
                raise ValueError(f"{name} fold class counts must reconcile to support")
        return self


class CalibrationAudit(StrictArtifactModel):
    """Exact CV semantics and membership evidence passed to sklearn."""

    training_membership_hash: HashRecord
    training_row_count: int = Field(gt=0)
    n_splits: int
    shuffle: bool
    random_state: int
    method: str
    ensemble: bool
    folds: list[CalibrationFoldAudit]

    @model_validator(mode="after")
    def validate_fold_contract(self) -> CalibrationAudit:
        if len(self.folds) != self.n_splits:
            raise ValueError("calibration audit must contain exactly one record per fold")
        if [fold.fold_index for fold in self.folds] != list(range(self.n_splits)):
            raise ValueError("calibration fold indices must be contiguous and ordered")
        for fold in self.folds:
            if fold.estimator_fit_count + fold.calibration_count != self.training_row_count:
                raise ValueError("each calibration fold must partition all training rows")
        return self


@dataclass(frozen=True)
class FittedModel:
    """The deployed calibrated estimator plus its train-only fold evidence."""

    estimator: CalibratedClassifierCV
    calibration_audit: CalibrationAudit


def _make_imputer(config_strategy: str, fill_value: str | None) -> SimpleImputer:
    return SimpleImputer(
        missing_values=np.nan,
        strategy=config_strategy,
        fill_value=fill_value,
        copy=True,
        add_indicator=False,
        keep_empty_features=False,
    )


def build_estimator_pipeline(config: TrainingConfig) -> Pipeline:
    """Build one preprocessing-plus-LogisticRegression estimator Pipeline."""

    preprocessing_config = config.preprocessing
    numeric_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                _make_imputer(
                    preprocessing_config.numeric_imputer.strategy,
                    preprocessing_config.numeric_imputer.fill_value,
                ),
            ),
            (
                "scaler",
                StandardScaler(
                    copy=preprocessing_config.numeric_scaler.copy_parameter,
                    with_mean=preprocessing_config.numeric_scaler.with_mean,
                    with_std=preprocessing_config.numeric_scaler.with_std,
                ),
            ),
        ],
        transform_input=preprocessing_config.pipeline.transform_input,
        memory=preprocessing_config.pipeline.memory,
        verbose=preprocessing_config.pipeline.verbose,
    )
    categorical_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                _make_imputer(
                    preprocessing_config.categorical_imputer.strategy,
                    preprocessing_config.categorical_imputer.fill_value,
                ),
            ),
            (
                "one_hot",
                OneHotEncoder(
                    categories=preprocessing_config.one_hot_encoder.categories,
                    drop=preprocessing_config.one_hot_encoder.drop,
                    sparse_output=preprocessing_config.one_hot_encoder.sparse_output,
                    dtype=np.float64,
                    handle_unknown=preprocessing_config.one_hot_encoder.handle_unknown,
                    min_frequency=preprocessing_config.one_hot_encoder.min_frequency,
                    max_categories=preprocessing_config.one_hot_encoder.max_categories,
                    feature_name_combiner=(
                        preprocessing_config.one_hot_encoder.feature_name_combiner
                    ),
                ),
            ),
        ],
        transform_input=preprocessing_config.pipeline.transform_input,
        memory=preprocessing_config.pipeline.memory,
        verbose=preprocessing_config.pipeline.verbose,
    )
    transformer_config = preprocessing_config.column_transformer
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, list(NUMERIC_FEATURES)),
            ("categorical", categorical_pipeline, list(CATEGORICAL_FEATURES)),
        ],
        remainder=transformer_config.remainder,
        sparse_threshold=transformer_config.sparse_threshold,
        n_jobs=transformer_config.n_jobs,
        transformer_weights=transformer_config.transformer_weights,
        verbose=transformer_config.verbose,
        verbose_feature_names_out=transformer_config.verbose_feature_names_out,
    )
    logistic_config = config.logistic_regression
    classifier = LogisticRegression(
        penalty=logistic_config.penalty,
        C=logistic_config.C,
        l1_ratio=logistic_config.l1_ratio,
        dual=logistic_config.dual,
        tol=logistic_config.tol,
        fit_intercept=logistic_config.fit_intercept,
        intercept_scaling=logistic_config.intercept_scaling,
        class_weight=logistic_config.class_weight,
        random_state=logistic_config.random_state,
        solver=logistic_config.solver,
        max_iter=logistic_config.max_iter,
        verbose=logistic_config.verbose,
        warm_start=logistic_config.warm_start,
        n_jobs=logistic_config.n_jobs,
    )
    return Pipeline(
        steps=[("preprocessor", preprocessor), ("classifier", classifier)],
        transform_input=preprocessing_config.pipeline.transform_input,
        memory=preprocessing_config.pipeline.memory,
        verbose=preprocessing_config.pipeline.verbose,
    )


def build_calibration_cv(config: TrainingConfig) -> StratifiedKFold:
    """Build the locked shuffled five-fold splitter without defaults."""

    calibration = config.calibration
    return StratifiedKFold(
        n_splits=calibration.n_splits,
        shuffle=calibration.shuffle,
        random_state=calibration.random_state,
    )


def build_calibrated_model(config: TrainingConfig) -> CalibratedClassifierCV:
    """Wrap the entire estimator Pipeline in explicit sigmoid calibration."""

    calibration = config.calibration
    return CalibratedClassifierCV(
        estimator=build_estimator_pipeline(config),
        method=calibration.method,
        cv=build_calibration_cv(config),
        n_jobs=calibration.n_jobs,
        ensemble=calibration.ensemble,
    )


def build_calibration_audit(
    training_features: pd.DataFrame,
    training_labels: pd.Series,
    config: TrainingConfig,
) -> CalibrationAudit:
    """Materialize the exact fold memberships that the configured CV will use."""

    event_ids = training_features.index.astype(str).tolist()
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("training feature index must contain unique event IDs")
    folds: list[CalibrationFoldAudit] = []
    cv = build_calibration_cv(config)
    labels_array = training_labels.to_numpy(dtype=int)
    for fold_index, (fit_indices, calibration_indices) in enumerate(
        cv.split(training_features, labels_array)
    ):
        fit_ids = [event_ids[int(index)] for index in fit_indices]
        calibration_ids = [event_ids[int(index)] for index in calibration_indices]
        if set(fit_ids) & set(calibration_ids):
            raise AssertionError("calibration fold fit and holdout memberships overlap")
        if set(fit_ids) | set(calibration_ids) != set(event_ids):
            raise AssertionError("calibration fold does not exhaust training membership")
        fit_labels = labels_array[fit_indices]
        calibration_labels = labels_array[calibration_indices]
        fit_counts = {"0": int((fit_labels == 0).sum()), "1": int((fit_labels == 1).sum())}
        calibration_counts = {
            "0": int((calibration_labels == 0).sum()),
            "1": int((calibration_labels == 1).sum()),
        }
        if 0 in fit_counts.values() or 0 in calibration_counts.values():
            raise ValueError("every calibration fold partition must contain both classes")
        folds.append(
            CalibrationFoldAudit(
                fold_index=fold_index,
                estimator_fit_count=len(fit_ids),
                calibration_count=len(calibration_ids),
                estimator_fit_membership_hash=membership_hash(fit_ids),
                calibration_membership_hash=membership_hash(calibration_ids),
                estimator_fit_class_counts=fit_counts,
                calibration_class_counts=calibration_counts,
            )
        )
    calibration = config.calibration
    return CalibrationAudit(
        training_membership_hash=membership_hash(event_ids),
        training_row_count=len(event_ids),
        n_splits=calibration.n_splits,
        shuffle=calibration.shuffle,
        random_state=calibration.random_state,
        method=calibration.method,
        ensemble=calibration.ensemble,
        folds=folds,
    )


def fit_calibrated_model(
    training_features: pd.DataFrame,
    training_labels: pd.Series,
    config: TrainingConfig,
) -> FittedModel:
    """Fit only the rows provided at the explicit training boundary."""

    if list(training_features.columns) != list(FEATURE_ORDER):
        raise ValueError("training features must use the exact ordered feature allowlist")
    audit = build_calibration_audit(training_features, training_labels, config)
    estimator = build_calibrated_model(config)
    estimator.fit(training_features, training_labels.to_numpy(dtype=int))
    return FittedModel(estimator=estimator, calibration_audit=audit)


def predict_positive_scores(
    estimator: CalibratedClassifierCV,
    features: pd.DataFrame,
) -> np.ndarray:
    """Return finite positive-class probabilities in row order."""

    if list(features.columns) != list(FEATURE_ORDER):
        raise ValueError("prediction features must use the exact ordered feature allowlist")
    probabilities = np.asarray(estimator.predict_proba(features), dtype=float)
    classes = np.asarray(estimator.classes_)
    positive_positions = np.flatnonzero(classes == 1)
    if len(positive_positions) != 1:
        raise ValueError("fitted estimator must expose exactly one positive class")
    scores = probabilities[:, int(positive_positions[0])]
    if not np.isfinite(scores).all() or ((scores < 0.0) | (scores > 1.0)).any():
        raise ValueError("calibrated scores must be finite and in [0, 1]")
    return scores
