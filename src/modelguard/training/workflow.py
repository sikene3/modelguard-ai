"""End-to-end deterministic Phase 02 generation and training workflow."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess  # nosec B404
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV

from modelguard.core.hashing import HashRecord, raw_file_hash, source_tree_hash
from modelguard.core.serialization import load_json_model, utc_now_iso, write_json
from modelguard.data.generator import (
    GENERATOR_VERSION,
    dataset_hash,
    generate_synthetic_data,
    read_dataset,
    write_dataset,
)
from modelguard.data.schema import (
    DATASET_COLUMNS,
    FEATURE_ORDER,
    ID_COLUMN,
    LABEL_COLUMN,
    DatasetManifest,
    QualityManifest,
    build_input_schema,
)
from modelguard.data.split import (
    SplitManifest,
    assignment_hash,
    build_split_manifest,
    create_split_assignments,
    read_split_assignments,
    verify_split_assignments,
    write_split_assignments,
)
from modelguard.data.validation import QUALITY_CHECKS, validate_dataset
from modelguard.training.baseline import BaselineProfile, build_baseline_profile
from modelguard.training.bundle import (
    BASELINE_FILENAME,
    CHECKSUM_FILENAME,
    MANIFEST_FILENAME,
    METRICS_FILENAME,
    MODEL_FILENAME,
    SCHEMA_FILENAME,
    THRESHOLD_FILENAME,
    BundleIdentity,
    GitState,
    ManifestLineage,
    ModelManifest,
    SoftwareVersions,
    build_immutable_bundle,
    inspect_bundle,
)
from modelguard.training.config import (
    ConfigManifest,
    TrainingConfig,
    load_training_config,
    training_config_hash,
)
from modelguard.training.evaluate import (
    MetricsContract,
    ThresholdContract,
    evaluate_held_out_test,
    lock_threshold,
    select_validation_threshold,
)
from modelguard.training.pipeline import (
    fit_calibrated_model,
    predict_positive_scores,
)
from modelguard.training.tracking import LocalMlflowRun

DATASET_FILENAME = "synthetic_fraud.csv"
DATASET_MANIFEST_FILENAME = "dataset_manifest.json"
QUALITY_MANIFEST_FILENAME = "quality_manifest.json"
CONFIG_MANIFEST_FILENAME = "config_manifest.json"
SPLIT_ASSIGNMENTS_FILENAME = "split_assignments.csv"
SPLIT_MANIFEST_FILENAME = "split_manifest.json"
DATA_ARTIFACT_FILENAMES = (
    DATASET_FILENAME,
    DATASET_MANIFEST_FILENAME,
    QUALITY_MANIFEST_FILENAME,
    CONFIG_MANIFEST_FILENAME,
    SPLIT_ASSIGNMENTS_FILENAME,
    SPLIT_MANIFEST_FILENAME,
)
EVALUATION_SEQUENCE = (
    "persisted_split_verified_before_fit",
    "training_rows_fit_and_calibrated_only",
    "validation_rows_scored",
    "validation_threshold_locked",
    "training_reference_distribution_scored_without_performance_claims",
    "held_out_test_scored_once",
)


@dataclass(frozen=True)
class DataArtifactPaths:
    root: Path

    @property
    def dataset(self) -> Path:
        return self.root / DATASET_FILENAME

    @property
    def dataset_manifest(self) -> Path:
        return self.root / DATASET_MANIFEST_FILENAME

    @property
    def quality_manifest(self) -> Path:
        return self.root / QUALITY_MANIFEST_FILENAME

    @property
    def config_manifest(self) -> Path:
        return self.root / CONFIG_MANIFEST_FILENAME

    @property
    def split_assignments(self) -> Path:
        return self.root / SPLIT_ASSIGNMENTS_FILENAME

    @property
    def split_manifest(self) -> Path:
        return self.root / SPLIT_MANIFEST_FILENAME


@dataclass(frozen=True)
class TrainingInputs:
    dataset: pd.DataFrame
    assignments: pd.DataFrame
    dataset_manifest: DatasetManifest
    quality_manifest: QualityManifest
    config_manifest: ConfigManifest
    split_manifest: SplitManifest
    paths: DataArtifactPaths


@dataclass(frozen=True)
class SplitFrames:
    training_features: pd.DataFrame
    training_labels: pd.Series
    validation_features: pd.DataFrame
    validation_labels: pd.Series
    test_features: pd.DataFrame
    test_labels: pd.Series


@dataclass(frozen=True)
class TrainingResult:
    bundle_path: Path
    identity: BundleIdentity
    mlflow_run_id: str
    mlflow_tracking_uri: str
    threshold: ThresholdContract
    metrics: MetricsContract
    baseline: BaselineProfile
    evaluation_sequence: tuple[str, ...]
    test_scores: np.ndarray


ScorePredictor = Callable[[CalibratedClassifierCV, pd.DataFrame], np.ndarray]
StageCallback = Callable[[str], None]


def generate_data_artifacts(config_path: Path, output_root: Path) -> DataArtifactPaths:
    """Persist dataset and its one canonical split atomically before any fitting."""

    config = load_training_config(config_path)
    target = output_root / "data"
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"generated data artifact directory already exists: {target}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".data.tmp-", dir=output_root))
    paths = DataArtifactPaths(temporary)
    try:
        generated = generate_synthetic_data(config.dataset.row_count, config.dataset.seed)
        validate_dataset(generated)
        write_dataset(paths.dataset, generated)
        persisted = read_dataset(paths.dataset)
        quality = validate_dataset(persisted)
        identity = dataset_hash(persisted)
        created_at = utc_now_iso()
        assignments = create_split_assignments(persisted, config.split)
        split_manifest = build_split_manifest(
            persisted,
            assignments,
            config.split,
            created_at=created_at,
        )
        write_split_assignments(paths.split_assignments, assignments)
        persisted_assignments = read_split_assignments(paths.split_assignments)
        verify_split_assignments(persisted, persisted_assignments, split_manifest)

        dataset_manifest = DatasetManifest(
            created_at=created_at,
            generator_version=GENERATOR_VERSION,
            generator_seed=config.dataset.seed,
            row_count=quality.row_count,
            columns=list(DATASET_COLUMNS),
            class_counts=quality.class_counts,
            dataset_hash=identity,
        )
        quality_manifest = QualityManifest(
            created_at=created_at,
            dataset_hash=identity,
            row_count=quality.row_count,
            class_counts=quality.class_counts,
            missing_counts=quality.missing_counts,
            checks=list(quality.checks),
        )
        config_manifest = ConfigManifest(
            created_at=created_at,
            configuration_hash=training_config_hash(config),
            configuration=config,
        )
        write_json(paths.dataset_manifest, dataset_manifest)
        write_json(paths.quality_manifest, quality_manifest)
        write_json(paths.config_manifest, config_manifest)
        write_json(paths.split_manifest, split_manifest)

        load_training_inputs(config, DataArtifactPaths(temporary))
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"generated data target appeared concurrently: {target}")
        os.rename(temporary, target)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return DataArtifactPaths(target)


def load_training_inputs(config: TrainingConfig, paths: DataArtifactPaths) -> TrainingInputs:
    """Recompute all identities and reject mismatches before an estimator can fit."""

    dataset = read_dataset(paths.dataset)
    quality = validate_dataset(dataset)
    assignments = read_split_assignments(paths.split_assignments)
    dataset_manifest = load_json_model(paths.dataset_manifest, DatasetManifest)
    quality_manifest = load_json_model(paths.quality_manifest, QualityManifest)
    config_manifest = load_json_model(paths.config_manifest, ConfigManifest)
    split_manifest = load_json_model(paths.split_manifest, SplitManifest)

    current_dataset_hash = dataset_hash(dataset)
    if dataset_manifest.dataset_hash != current_dataset_hash:
        raise ValueError("persisted dataset hash does not match dataset manifest")
    if (
        dataset_manifest.row_count != quality.row_count
        or dataset_manifest.class_counts != quality.class_counts
    ):
        raise ValueError("dataset manifest support does not match validated dataset")
    if dataset_manifest.columns != list(DATASET_COLUMNS):
        raise ValueError("dataset manifest columns differ from the strict schema")
    if (
        dataset_manifest.generator_seed != config.dataset.seed
        or dataset_manifest.generator_version != config.dataset.generator_version
        or dataset_manifest.row_count != config.dataset.row_count
    ):
        raise ValueError("dataset manifest does not match configured generation parameters")
    if quality_manifest.dataset_hash != current_dataset_hash:
        raise ValueError("quality manifest refers to a different dataset")
    if (
        quality_manifest.row_count != quality.row_count
        or quality_manifest.class_counts != quality.class_counts
        or quality_manifest.missing_counts != quality.missing_counts
        or quality_manifest.checks != list(QUALITY_CHECKS)
    ):
        raise ValueError("quality manifest facts do not match current validation")
    current_config_hash = training_config_hash(config)
    if (
        config_manifest.configuration != config
        or config_manifest.configuration_hash != current_config_hash
    ):
        raise ValueError("configuration manifest hash or parameters do not match")
    split_config = config.split
    if (
        split_manifest.strategy != split_config.strategy
        or split_manifest.train_fraction != split_config.train_fraction
        or split_manifest.validation_fraction != split_config.validation_fraction
        or split_manifest.test_fraction != split_config.test_fraction
        or split_manifest.train_remainder_seed != split_config.train_remainder_seed
        or split_manifest.validation_test_seed != split_config.validation_test_seed
    ):
        raise ValueError("split manifest does not match configured split parameters")
    verify_split_assignments(dataset, assignments, split_manifest)
    expected_assignments = create_split_assignments(dataset, split_config)
    if assignment_hash(assignments) != assignment_hash(expected_assignments):
        raise ValueError("persisted split assignment does not match the canonical configured split")
    return TrainingInputs(
        dataset=dataset,
        assignments=assignments,
        dataset_manifest=dataset_manifest,
        quality_manifest=quality_manifest,
        config_manifest=config_manifest,
        split_manifest=split_manifest,
        paths=paths,
    )


def materialize_split_frames(inputs: TrainingInputs) -> SplitFrames:
    """Create explicit ID-indexed frames; event_id and label never enter the allowlist."""

    indexed = inputs.dataset.set_index(ID_COLUMN, drop=True)

    def frame(split_name: str) -> tuple[pd.DataFrame, pd.Series]:
        event_ids = (
            inputs.assignments.loc[inputs.assignments["split"] == split_name, ID_COLUMN]
            .astype(str)
            .tolist()
        )
        selected = indexed.loc[event_ids]
        features = selected.loc[:, FEATURE_ORDER].copy()
        features.index.name = ID_COLUMN
        labels = selected[LABEL_COLUMN].astype(int).copy()
        labels.index.name = ID_COLUMN
        return features, labels

    training_features, training_labels = frame("train")
    validation_features, validation_labels = frame("validation")
    test_features, test_labels = frame("test")
    return SplitFrames(
        training_features=training_features,
        training_labels=training_labels,
        validation_features=validation_features,
        validation_labels=validation_labels,
        test_features=test_features,
        test_labels=test_labels,
    )


def _git_state(repository_root: Path) -> GitState:
    git_executable = shutil.which("git")
    if git_executable is None:
        return GitState(
            available=False,
            sha=None,
            dirty=None,
            reason="git_executable_unavailable",
        )
    sha_result = subprocess.run(  # nosec B603
        [git_executable, "rev-parse", "HEAD"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if sha_result.returncode != 0:
        return GitState(
            available=False,
            sha=None,
            dirty=None,
            reason="git_revision_unavailable_or_repository_has_no_commit",
        )
    status_result = subprocess.run(  # nosec B603
        [git_executable, "status", "--porcelain"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if status_result.returncode != 0:
        return GitState(
            available=False,
            sha=None,
            dirty=None,
            reason="git_dirty_state_unavailable",
        )
    return GitState(
        available=True,
        sha=sha_result.stdout.strip(),
        dirty=bool(status_result.stdout),
        reason=None,
    )


def _software_versions() -> SoftwareVersions:
    return SoftwareVersions(
        python=platform.python_version(),
        scikit_learn=sklearn.__version__,
        numpy=np.__version__,
        pandas=pd.__version__,
        joblib=joblib.__version__,
    )


def _write_evaluation_plots(training_dir: Path, metrics: MetricsContract) -> tuple[Path, Path]:
    training_dir.mkdir(parents=True, exist_ok=True)
    reliability_path = training_dir / "reliability_plot.html"
    observed_values = [
        item.observed_prevalence.value or 0.0 for item in metrics.held_out_test.reliability_bins
    ]
    score_values = [item.mean_score.value or 0.0 for item in metrics.held_out_test.reliability_bins]
    bars = "".join(
        f'<rect x="{40 + index * 48}" y="{330 - observed * 280:.2f}" width="18" '
        f'height="{observed * 280:.2f}" fill="#2b6cb0"/>'
        f'<rect x="{59 + index * 48}" y="{330 - score * 280:.2f}" width="18" '
        f'height="{score * 280:.2f}" fill="#ed8936"/>'
        for index, (observed, score) in enumerate(zip(observed_values, score_values, strict=True))
    )
    reliability_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Held-out reliability</title>"
        "<h1>Held-out test reliability bins</h1>"
        "<p>Blue: observed prevalence. Orange: mean calibrated score. Empty bins plot at zero.</p>"
        f"<svg viewBox='0 0 560 370' role='img' aria-label='Reliability plot'>{bars}"
        "<line x1='40' y1='330' x2='530' y2='330' stroke='black'/></svg>",
        encoding="utf-8",
    )

    confusion_path = training_dir / "confusion_matrix_plot.html"
    counts = metrics.held_out_test.confusion_counts
    confusion_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Held-out confusion matrix</title>"
        "<h1>Held-out test confusion matrix at locked threshold</h1>"
        "<table border='1' cellpadding='12'><tr><th></th><th>Predicted low</th>"
        "<th>Predicted high</th></tr>"
        f"<tr><th>Actual low</th><td>{counts.true_negatives}</td>"
        f"<td>{counts.false_positives}</td></tr>"
        f"<tr><th>Actual high</th><td>{counts.false_negatives}</td>"
        f"<td>{counts.true_positives}</td></tr></table>",
        encoding="utf-8",
    )
    return reliability_path, confusion_path


def _format_metric(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.6f}"


def _write_cards(
    training_dir: Path,
    inputs: TrainingInputs,
    config: TrainingConfig,
    metrics: MetricsContract,
) -> tuple[Path, Path]:
    data_card = training_dir / "data_card.md"
    data_card.write_text(
        "# Synthetic data card\n\n"
        f"- Generator: `{config.dataset.generator_version}`\n"
        f"- Rows: {inputs.dataset_manifest.row_count}\n"
        f"- Dataset SHA-256: `{inputs.dataset_manifest.dataset_hash.digest}`\n"
        f"- Generator seed: {config.dataset.seed}\n"
        "- Rows are independently generated from the seed plus row index; event IDs are stable.\n"
        "- Latent logits/probabilities and generator indices are never persisted.\n"
        "- This dataset is synthetic and must not be treated as representative payment data.\n",
        encoding="utf-8",
    )
    test_metrics = metrics.held_out_test
    model_card = training_dir / "model_card.md"
    model_card.write_text(
        "# Model card\n\n"
        f"- Model version: `{config.model_version}`\n"
        "- Estimator: preprocessing plus LogisticRegression in one sklearn Pipeline, wrapped by "
        "five-fold train-only sigmoid CalibratedClassifierCV with ensemble enabled.\n"
        f"- Locked validation threshold: {test_metrics.threshold:.3f}\n"
        f"- Held-out average precision: {_format_metric(test_metrics.average_precision.value)}\n"
        f"- Held-out prevalence: {_format_metric(test_metrics.prevalence.value)}\n"
        f"- Held-out AP lift: {_format_metric(test_metrics.ap_lift.value)}\n"
        f"- Held-out synthetic cost/event: "
        f"{_format_metric(test_metrics.synthetic_cost_per_event.value)}\n"
        "- Headline results are from the one-time held-out test evaluation. Training-reference "
        "scores/decisions are distribution baselines only, not performance evidence.\n"
        "- Scores are calibrated only for this synthetic demo distribution and are not guaranteed "
        "real-world fraud probabilities or an economically optimal policy.\n",
        encoding="utf-8",
    )
    return data_card, model_card


def _source_lineage(repository_root: Path) -> HashRecord:
    source_root = repository_root / "src" / "modelguard"
    paths = [
        path
        for path in source_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    return source_tree_hash(
        repository_root,
        paths,
        exclusions=[
            ".git/**",
            "artifacts/**",
            "tests/**",
            "reports/**",
            "configs/** (configuration hashed separately)",
            "Python bytecode and __pycache__",
        ],
    )


def train_from_artifacts(
    config_path: Path,
    output_root: Path,
    repository_root: Path,
    *,
    score_predictor: ScorePredictor = predict_positive_scores,
    stage_callback: StageCallback | None = None,
) -> TrainingResult:
    """Fit, lock, evaluate once, track, bundle, and verify the audited workflow."""

    config = load_training_config(config_path)
    bundle_parent = output_root / "model-bundles"
    target_bundle = bundle_parent / config.model_version
    if target_bundle.exists() or target_bundle.is_symlink():
        raise FileExistsError(f"immutable model bundle already exists: {target_bundle}")
    training_dir = output_root / "training" / config.model_version
    if training_dir.exists() or training_dir.is_symlink():
        raise FileExistsError(f"training evidence directory already exists: {training_dir}")
    inputs = load_training_inputs(config, DataArtifactPaths(output_root / "data"))
    frames = materialize_split_frames(inputs)
    events: list[str] = []

    def emit(event: str) -> None:
        events.append(event)
        if stage_callback is not None:
            stage_callback(event)

    emit(EVALUATION_SEQUENCE[0])
    tracking = LocalMlflowRun(
        output_root,
        config,
        tags={
            "model_version": config.model_version,
            "dataset_sha256": inputs.dataset_manifest.dataset_hash.digest,
            "split_sha256": inputs.split_manifest.assignment_hash.digest,
            "public_headline_scope": "held_out_test",
            "calibration_scope": "training_only",
            "threshold_selection_scope": "validation_only",
            "mlflow.autolog": "false",
        },
    )
    try:
        tracking.log_configuration(config)
        fitted = fit_calibrated_model(
            frames.training_features,
            frames.training_labels,
            config,
        )
        emit(EVALUATION_SEQUENCE[1])
        validation_scores = score_predictor(fitted.estimator, frames.validation_features)
        emit(EVALUATION_SEQUENCE[2])
        threshold_evidence = select_validation_threshold(
            frames.validation_labels.to_numpy(dtype=int),
            validation_scores,
            frames.validation_features.index.astype(str).tolist(),
            config.threshold,
        )
        created_at = utc_now_iso()
        threshold = lock_threshold(
            config.model_version,
            threshold_evidence,
            locked_at=created_at,
        )
        emit(EVALUATION_SEQUENCE[3])
        training_scores = score_predictor(fitted.estimator, frames.training_features)
        baseline = build_baseline_profile(
            frames.training_features,
            training_scores,
            threshold,
            config.baseline,
            model_version=config.model_version,
            created_at=created_at,
        )
        emit(EVALUATION_SEQUENCE[4])
        test_scores = score_predictor(fitted.estimator, frames.test_features)
        emit(EVALUATION_SEQUENCE[5])
        held_out_test = evaluate_held_out_test(
            frames.test_labels.to_numpy(dtype=int),
            test_scores,
            threshold,
        )
        metrics = MetricsContract(
            model_version=config.model_version,
            created_at=created_at,
            held_out_test=held_out_test,
            validation_threshold_selection=threshold_evidence,
        )
        input_schema = build_input_schema(config.model_version)

        training_dir.mkdir(parents=True, exist_ok=False)
        reliability_plot, confusion_plot = _write_evaluation_plots(training_dir, metrics)
        data_card, model_card = _write_cards(training_dir, inputs, config, metrics)
        tracking.log_evaluation(held_out_test, threshold_evidence)
        for filename in DATA_ARTIFACT_FILENAMES:
            tracking.log_artifact(inputs.paths.root / filename, artifact_path="data")
        for artifact in (reliability_plot, confusion_plot):
            tracking.log_artifact(artifact, artifact_path="plots")
        for artifact in (data_card, model_card):
            tracking.log_artifact(artifact, artifact_path="cards")

        repository_root = repository_root.resolve()
        uv_lock_path = repository_root / "uv.lock"
        if not uv_lock_path.is_file():
            raise FileNotFoundError("uv.lock is required for model lineage")
        source_hash = _source_lineage(repository_root)
        git_state = _git_state(repository_root)
        split_manifest_hash = raw_file_hash(inputs.paths.split_manifest)

        def manifest_factory(payload_hashes: dict[str, HashRecord]) -> ModelManifest:
            lineage = ManifestLineage(
                dataset_hash=inputs.dataset_manifest.dataset_hash,
                dataset_manifest_hash=raw_file_hash(inputs.paths.dataset_manifest),
                configuration_hash=inputs.config_manifest.configuration_hash,
                configuration_manifest_hash=raw_file_hash(inputs.paths.config_manifest),
                quality_manifest_hash=raw_file_hash(inputs.paths.quality_manifest),
                split_assignment_hash=inputs.split_manifest.assignment_hash,
                split_manifest_hash=split_manifest_hash,
                input_schema_hash=payload_hashes[SCHEMA_FILENAME],
                baseline_profile_hash=payload_hashes[BASELINE_FILENAME],
                source_tree_hash=source_hash,
                uv_lock_hash=raw_file_hash(uv_lock_path),
            )
            return ModelManifest(
                created_at=created_at,
                model_version=config.model_version,
                feature_order=list(FEATURE_ORDER),
                configuration=config,
                seeds={
                    "dataset_seed": config.dataset.seed,
                    "train_remainder_seed": config.split.train_remainder_seed,
                    "validation_test_seed": config.split.validation_test_seed,
                    "calibration_seed": config.calibration.random_state,
                    "logistic_regression_seed": config.logistic_regression.random_state,
                },
                split_manifest=inputs.split_manifest,
                calibration_audit=fitted.calibration_audit,
                evaluation_sequence=events,
                mlflow_run_id=tracking.run_id,
                software_versions=_software_versions(),
                git=git_state,
                lineage=lineage,
                bundle_payload_hashes=payload_hashes,
            )

        bundle_path = build_immutable_bundle(
            bundle_parent,
            model_version=config.model_version,
            estimator=fitted.estimator,
            input_schema=input_schema,
            metrics=metrics,
            threshold=threshold,
            baseline=baseline,
            manifest_factory=manifest_factory,
        )
        metadata = inspect_bundle(bundle_path)
        for filename in (
            MODEL_FILENAME,
            MANIFEST_FILENAME,
            SCHEMA_FILENAME,
            METRICS_FILENAME,
            THRESHOLD_FILENAME,
            BASELINE_FILENAME,
            CHECKSUM_FILENAME,
        ):
            tracking.log_artifact(bundle_path / filename, artifact_path="bundle")
        tracking.set_tag("manifest_sha256", metadata.identity.manifest_sha256)
        tracking.set_tag("bundle_identity", metadata.identity.model_dump_json())
        tracking.finish()
    except BaseException:
        tracking.fail()
        raise
    return TrainingResult(
        bundle_path=bundle_path,
        identity=metadata.identity,
        mlflow_run_id=tracking.run_id,
        mlflow_tracking_uri=tracking.tracking_uri,
        threshold=threshold,
        metrics=metrics,
        baseline=baseline,
        evaluation_sequence=tuple(events),
        test_scores=test_scores,
    )
