"""Persisted split, feature boundary, and calibration contract tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import StratifiedKFold

from modelguard.core.serialization import write_json
from modelguard.data.generator import generate_synthetic_data, read_dataset, write_dataset
from modelguard.data.schema import FEATURE_ORDER, ID_COLUMN, LABEL_COLUMN
from modelguard.data.split import (
    SPLIT_NAMES,
    build_split_manifest,
    create_split_assignments,
    membership_hash,
    read_split_assignments,
    verify_split_assignments,
    write_split_assignments,
)
from modelguard.training.config import TrainingConfig
from modelguard.training.evaluate import select_validation_threshold
from modelguard.training.pipeline import (
    build_estimator_pipeline,
    fit_calibrated_model,
    predict_positive_scores,
)
from modelguard.training.workflow import (
    DataArtifactPaths,
    generate_data_artifacts,
    load_training_inputs,
)


def _small_training_config(config: TrainingConfig, *, row_count: int) -> TrainingConfig:
    return config.model_copy(
        update={"dataset": config.dataset.model_copy(update={"row_count": row_count})}
    )


def _split_frame(
    dataset: pd.DataFrame,
    assignments: pd.DataFrame,
    split_name: str,
) -> tuple[pd.DataFrame, pd.Series]:
    ids = assignments.loc[assignments["split"] == split_name, ID_COLUMN].astype(str).tolist()
    selected = dataset.set_index(ID_COLUMN).loc[ids]
    return selected.loc[:, FEATURE_ORDER].copy(), selected[LABEL_COLUMN].astype(int).copy()


def test_split_is_deterministic_stratified_disjoint_and_exhaustive(
    training_config: TrainingConfig,
) -> None:
    config = _small_training_config(training_config, row_count=800)
    dataset = generate_synthetic_data(config.dataset.row_count, config.dataset.seed)
    first = create_split_assignments(dataset, config.split)
    second = create_split_assignments(
        dataset.sample(frac=1.0, random_state=9).reset_index(drop=True), config.split
    )
    pd.testing.assert_frame_equal(first, second)
    manifest = build_split_manifest(dataset, first, config.split, created_at="2026-01-01T00:00:00Z")
    verify_split_assignments(dataset, first, manifest)

    memberships = {
        name: set(first.loc[first["split"] == name, ID_COLUMN].astype(str)) for name in SPLIT_NAMES
    }
    assert not (memberships["train"] & memberships["validation"])
    assert not (memberships["train"] & memberships["test"])
    assert not (memberships["validation"] & memberships["test"])
    assert set.union(*memberships.values()) == set(dataset[ID_COLUMN].astype(str))
    for summary in manifest.splits.values():
        assert summary.class_counts["0"] > 0
        assert summary.class_counts["1"] > 0


def test_dataset_hash_mismatch_blocks_training_before_fit(
    tmp_path: Path,
    repository_root: Path,
    training_config: TrainingConfig,
) -> None:
    config = _small_training_config(training_config, row_count=500)
    config_path = tmp_path / "config.json"
    write_json(config_path, config)
    output_root = tmp_path / "artifacts"
    paths = generate_data_artifacts(config_path, output_root)
    tampered = read_dataset(paths.dataset)
    tampered.loc[0, "amount"] = float(tampered.loc[0, "amount"]) + 1.0
    write_dataset(paths.dataset, tampered)

    with pytest.raises(ValueError, match="dataset hash"):
        load_training_inputs(config, DataArtifactPaths(output_root / "data"))


def test_internally_consistent_noncanonical_split_is_rejected_before_fit(
    tmp_path: Path,
    training_config: TrainingConfig,
) -> None:
    config = _small_training_config(training_config, row_count=500)
    config_path = tmp_path / "config.json"
    write_json(config_path, config)
    output_root = tmp_path / "artifacts"
    paths = generate_data_artifacts(config_path, output_root)
    dataset = read_dataset(paths.dataset)
    assignments = read_split_assignments(paths.split_assignments)
    joined = assignments.merge(
        dataset[[ID_COLUMN, LABEL_COLUMN]], on=ID_COLUMN, validate="one_to_one"
    )
    validation_row = joined.loc[
        (joined["split"] == "validation") & (joined[LABEL_COLUMN] == 0)
    ].iloc[0]
    test_row = joined.loc[(joined["split"] == "test") & (joined[LABEL_COLUMN] == 0)].iloc[0]
    assignments.loc[assignments[ID_COLUMN] == validation_row[ID_COLUMN], "split"] = "test"
    assignments.loc[assignments[ID_COLUMN] == test_row[ID_COLUMN], "split"] = "validation"
    changed_manifest = build_split_manifest(
        dataset,
        assignments,
        config.split,
        created_at="2026-01-01T00:00:00Z",
    )
    write_split_assignments(paths.split_assignments, assignments)
    write_json(paths.split_manifest, changed_manifest)

    with pytest.raises(ValueError, match="canonical configured split"):
        load_training_inputs(config, DataArtifactPaths(output_root / "data"))


def test_fit_boundary_and_calibration_are_exactly_training_only(
    training_config: TrainingConfig,
) -> None:
    config = _small_training_config(training_config, row_count=650)
    dataset = generate_synthetic_data(config.dataset.row_count, config.dataset.seed)
    assignments = create_split_assignments(dataset, config.split)
    training_features, training_labels = _split_frame(dataset, assignments, "train")
    fitted = fit_calibrated_model(training_features, training_labels, config)

    expected_ids = training_features.index.astype(str).tolist()
    audit = fitted.calibration_audit
    assert audit.training_membership_hash == membership_hash(expected_ids)
    assert audit.training_row_count == len(expected_ids)
    assert audit.n_splits == 5
    assert audit.shuffle is True
    assert audit.method == "sigmoid"
    assert audit.ensemble is True
    assert len(audit.folds) == 5
    assert all(0 not in fold.estimator_fit_class_counts.values() for fold in audit.folds)
    assert all(0 not in fold.calibration_class_counts.values() for fold in audit.folds)

    assert fitted.estimator.method == "sigmoid"
    assert fitted.estimator.ensemble is True
    assert fitted.estimator.n_jobs is None
    assert isinstance(fitted.estimator.cv, StratifiedKFold)
    assert fitted.estimator.cv.n_splits == 5
    assert fitted.estimator.cv.shuffle is True
    assert fitted.estimator.cv.random_state == config.calibration.random_state


def test_feature_allowlist_and_all_classifier_parameters_are_explicit(
    training_config: TrainingConfig,
) -> None:
    assert training_config.feature_allowlist == list(FEATURE_ORDER)
    assert ID_COLUMN not in training_config.feature_allowlist
    assert LABEL_COLUMN not in training_config.feature_allowlist
    assert "split" not in training_config.feature_allowlist
    assert "latent_probability" not in training_config.feature_allowlist

    pipeline = build_estimator_pipeline(training_config)
    classifier = pipeline.named_steps["classifier"]
    parameters = classifier.get_params(deep=False)
    configured = training_config.logistic_regression.model_dump(mode="python")
    assert parameters == configured
    assert parameters["class_weight"] is None


def test_non_training_changes_cannot_change_the_fitted_model_or_validation_threshold(
    training_config: TrainingConfig,
) -> None:
    config = _small_training_config(training_config, row_count=600)
    original = generate_synthetic_data(config.dataset.row_count, config.dataset.seed)
    assignments = create_split_assignments(original, config.split)
    changed = original.copy()
    non_training_ids = set(assignments.loc[assignments["split"] != "train", ID_COLUMN].astype(str))
    mask = changed[ID_COLUMN].astype(str).isin(non_training_ids)
    changed.loc[mask, "amount"] = 25_000.0
    changed.loc[mask, "device_risk_score"] = 0.0

    first_features, first_labels = _split_frame(original, assignments, "train")
    second_features, second_labels = _split_frame(changed, assignments, "train")
    pd.testing.assert_frame_equal(first_features, second_features)
    pd.testing.assert_series_equal(first_labels, second_labels)
    first_model = fit_calibrated_model(first_features, first_labels, config).estimator
    second_model = fit_calibrated_model(second_features, second_labels, config).estimator
    np.testing.assert_allclose(
        predict_positive_scores(first_model, first_features),
        predict_positive_scores(second_model, first_features),
        rtol=0.0,
        atol=0.0,
    )

    validation_features, validation_labels = _split_frame(original, assignments, "validation")
    validation_scores = predict_positive_scores(first_model, validation_features)
    before_test_change = select_validation_threshold(
        validation_labels.to_numpy(dtype=int),
        validation_scores,
        validation_features.index.astype(str).tolist(),
        config.threshold,
    )
    changed.loc[assignments["split"].eq("test").to_numpy(), "amount"] = 0.01
    after_test_change = select_validation_threshold(
        validation_labels.to_numpy(dtype=int),
        validation_scores,
        validation_features.index.astype(str).tolist(),
        config.threshold,
    )
    assert before_test_change == after_test_change
