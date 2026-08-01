"""Immutable seven-file model bundle construction and ordered verification."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import joblib
import numpy as np
import pandas as pd
from pydantic import Field, model_validator
from sklearn.calibration import CalibratedClassifierCV

from modelguard.core.hashing import HashRecord, raw_file_hash, sha256_file
from modelguard.core.serialization import (
    StrictArtifactModel,
    load_json_model,
    write_json,
)
from modelguard.data.schema import FEATURE_ORDER, InputSchemaContract
from modelguard.data.split import SplitManifest
from modelguard.training.baseline import BaselineProfile
from modelguard.training.config import TrainingConfig, training_config_hash
from modelguard.training.evaluate import MetricsContract, ThresholdContract
from modelguard.training.pipeline import CalibrationAudit

MODEL_FILENAME = "model.joblib"
MANIFEST_FILENAME = "manifest.json"
SCHEMA_FILENAME = "input_schema.json"
METRICS_FILENAME = "metrics.json"
THRESHOLD_FILENAME = "threshold.json"
BASELINE_FILENAME = "baseline_profile.json"
CHECKSUM_FILENAME = "checksums.sha256"
PAYLOAD_FILENAMES = frozenset(
    {
        MODEL_FILENAME,
        MANIFEST_FILENAME,
        SCHEMA_FILENAME,
        METRICS_FILENAME,
        THRESHOLD_FILENAME,
        BASELINE_FILENAME,
    }
)
HASHED_BY_MANIFEST_FILENAMES = frozenset(PAYLOAD_FILENAMES - {MANIFEST_FILENAME})
EXPECTED_FILENAMES = PAYLOAD_FILENAMES | {CHECKSUM_FILENAME}
CHECKSUM_LINE_PATTERN = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_.-]+)$")


class BundleIdentity(StrictArtifactModel):
    model_version: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SoftwareVersions(StrictArtifactModel):
    python: str
    scikit_learn: str
    numpy: str
    pandas: str
    joblib: str


class GitState(StrictArtifactModel):
    available: bool
    sha: str | None
    dirty: bool | None
    reason: str | None

    @model_validator(mode="after")
    def validate_availability(self) -> GitState:
        if self.available and (self.sha is None or self.dirty is None or self.reason is not None):
            raise ValueError("available Git state requires sha/dirty and no reason")
        if not self.available and (
            self.sha is not None or self.dirty is not None or self.reason is None
        ):
            raise ValueError("unavailable Git state requires only a reason")
        return self


class ManifestLineage(StrictArtifactModel):
    dataset_hash: HashRecord
    dataset_manifest_hash: HashRecord
    configuration_hash: HashRecord
    configuration_manifest_hash: HashRecord
    quality_manifest_hash: HashRecord
    split_assignment_hash: HashRecord
    split_manifest_hash: HashRecord
    input_schema_hash: HashRecord
    baseline_profile_hash: HashRecord
    source_tree_hash: HashRecord
    uv_lock_hash: HashRecord


class ModelManifest(StrictArtifactModel):
    """Complete lineage and training contract for one immutable model version."""

    contract_version: Literal["modelguard.model-manifest.v1"] = "modelguard.model-manifest.v1"
    created_at: str
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    feature_order: list[str]
    id_column: Literal["event_id"] = "event_id"
    label_column: Literal["is_fraud"] = "is_fraud"
    configuration: TrainingConfig
    seeds: dict[str, int]
    split_manifest: SplitManifest
    calibration_audit: CalibrationAudit
    evaluation_sequence: list[str]
    mlflow_run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    mlflow_tracking_scheme: Literal["file"] = "file"
    mlflow_autolog_used: Literal[False] = False
    software_versions: SoftwareVersions
    git: GitState
    lineage: ManifestLineage
    bundle_payload_hashes: dict[str, HashRecord]
    authenticity_notice: Literal[
        "checksums_detect_corruption_but_do_not_authenticate_the_model_origin"
    ] = "checksums_detect_corruption_but_do_not_authenticate_the_model_origin"

    @model_validator(mode="after")
    def validate_manifest(self) -> ModelManifest:
        if self.feature_order != list(FEATURE_ORDER):
            raise ValueError("manifest feature order must match the locked allowlist")
        if self.configuration.model_version != self.model_version:
            raise ValueError("manifest and configuration model versions differ")
        if set(self.bundle_payload_hashes) != HASHED_BY_MANIFEST_FILENAMES:
            raise ValueError("manifest must hash every non-manifest/non-checksum payload")
        expected_sequence = [
            "persisted_split_verified_before_fit",
            "training_rows_fit_and_calibrated_only",
            "validation_rows_scored",
            "validation_threshold_locked",
            "training_reference_distribution_scored_without_performance_claims",
            "held_out_test_scored_once",
        ]
        if self.evaluation_sequence != expected_sequence:
            raise ValueError("evaluation sequence does not match the locked statistical contract")
        config = self.configuration
        expected_seeds = {
            "dataset_seed": config.dataset.seed,
            "train_remainder_seed": config.split.train_remainder_seed,
            "validation_test_seed": config.split.validation_test_seed,
            "calibration_seed": config.calibration.random_state,
            "logistic_regression_seed": config.logistic_regression.random_state,
        }
        if self.seeds != expected_seeds:
            raise ValueError("manifest seeds do not match the embedded configuration")
        split = self.split_manifest
        split_config = config.split
        if (
            split.strategy != split_config.strategy
            or split.train_fraction != split_config.train_fraction
            or split.validation_fraction != split_config.validation_fraction
            or split.test_fraction != split_config.test_fraction
            or split.train_remainder_seed != split_config.train_remainder_seed
            or split.validation_test_seed != split_config.validation_test_seed
        ):
            raise ValueError("embedded split manifest does not match the configuration")
        calibration = self.calibration_audit
        calibration_config = config.calibration
        if (
            calibration.n_splits != calibration_config.n_splits
            or calibration.shuffle != calibration_config.shuffle
            or calibration.random_state != calibration_config.random_state
            or calibration.method != calibration_config.method
            or calibration.ensemble != calibration_config.ensemble
        ):
            raise ValueError("calibration audit does not match the configured calibration")
        return self


class BundleVerificationError(ValueError):
    """Raised when ordered verification blocks a bundle before prediction."""


class ProbabilityModel(Protocol):
    classes_: Any

    def predict_proba(self, features: pd.DataFrame) -> Any:
        """Return class probabilities."""


@dataclass(frozen=True)
class ValidatedBundleMetadata:
    """Strict bundle payloads validated without deserializing joblib."""

    path: Path
    identity: BundleIdentity
    manifest: ModelManifest
    input_schema: InputSchemaContract
    metrics: MetricsContract
    threshold: ThresholdContract
    baseline: BaselineProfile


@dataclass(frozen=True)
class VerifiedBundle:
    """Trusted-origin model loaded only after complete metadata verification."""

    metadata: ValidatedBundleMetadata
    model: ProbabilityModel
    smoke_score: float


ManifestFactory = Callable[[dict[str, HashRecord]], ModelManifest]
ModelDumper = Callable[[Any, Path], Any]
ModelLoader = Callable[[Path], Any]


def _default_model_dumper(model: Any, path: Path) -> Any:
    return joblib.dump(model, path, compress=3, protocol=5)


def _default_model_loader(path: Path) -> Any:
    return joblib.load(path)


def _write_checksums(directory: Path) -> None:
    lines = [
        f"{sha256_file(directory / filename)}  {filename}" for filename in sorted(PAYLOAD_FILENAMES)
    ]
    (directory / CHECKSUM_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_immutable_bundle(
    bundle_parent: Path,
    *,
    model_version: str,
    estimator: CalibratedClassifierCV,
    input_schema: InputSchemaContract,
    metrics: MetricsContract,
    threshold: ThresholdContract,
    baseline: BaselineProfile,
    manifest_factory: ManifestFactory,
    model_dumper: ModelDumper = _default_model_dumper,
) -> Path:
    """Build in a temporary sibling, verify, and atomically publish without overwrite."""

    target = bundle_parent / model_version
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"immutable model bundle already exists: {target}")
    bundle_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{model_version}.tmp-", dir=bundle_parent))
    try:
        model_dumper(estimator, temporary / MODEL_FILENAME)
        write_json(temporary / SCHEMA_FILENAME, input_schema)
        write_json(temporary / METRICS_FILENAME, metrics)
        write_json(temporary / THRESHOLD_FILENAME, threshold)
        write_json(temporary / BASELINE_FILENAME, baseline)
        payload_hashes = {
            filename: raw_file_hash(temporary / filename)
            for filename in sorted(HASHED_BY_MANIFEST_FILENAMES)
        }
        manifest = manifest_factory(payload_hashes)
        write_json(temporary / MANIFEST_FILENAME, manifest)
        _write_checksums(temporary)
        verify_bundle(temporary, trusted_origin=True)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"immutable model bundle appeared concurrently: {target}")
        os.rename(temporary, target)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return target


def _validate_structure(bundle_path: Path) -> None:
    if bundle_path.is_symlink():
        raise BundleVerificationError("bundle root cannot be a symlink")
    if not bundle_path.is_dir():
        raise BundleVerificationError("bundle path must be an existing directory")
    entries = list(bundle_path.iterdir())
    symlinks = sorted(entry.name for entry in entries if entry.is_symlink())
    if symlinks:
        raise BundleVerificationError(f"bundle contains forbidden symlinks: {symlinks}")
    actual = {entry.name for entry in entries}
    missing = sorted(EXPECTED_FILENAMES - actual)
    extra = sorted(actual - EXPECTED_FILENAMES)
    if missing or extra:
        raise BundleVerificationError(
            f"bundle file set mismatch (missing={missing}, extra={extra})"
        )
    non_files = sorted(entry.name for entry in entries if not entry.is_file())
    if non_files:
        raise BundleVerificationError(f"bundle entries must be regular files: {non_files}")


def _parse_and_verify_checksums(bundle_path: Path) -> None:
    checksum_text = (bundle_path / CHECKSUM_FILENAME).read_text(encoding="utf-8")
    if not checksum_text.endswith("\n"):
        raise BundleVerificationError("checksum file must end with one newline")
    lines = checksum_text.splitlines()
    if len(lines) != len(PAYLOAD_FILENAMES):
        raise BundleVerificationError("checksum file must contain one line per payload")
    expected_digests: dict[str, str] = {}
    for line in lines:
        match = CHECKSUM_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise BundleVerificationError("invalid checksum-file syntax")
        digest, filename = match.groups()
        if filename in expected_digests:
            raise BundleVerificationError(f"duplicate checksum entry: {filename}")
        expected_digests[filename] = digest
    if set(expected_digests) != PAYLOAD_FILENAMES:
        raise BundleVerificationError("checksum entries do not match exact payload set")
    for filename, expected_digest in expected_digests.items():
        if sha256_file(bundle_path / filename) != expected_digest:
            raise BundleVerificationError(f"byte checksum mismatch: {filename}")


def _parse_contracts(
    bundle_path: Path,
) -> tuple[ModelManifest, InputSchemaContract, MetricsContract, ThresholdContract, BaselineProfile]:
    try:
        manifest = load_json_model(bundle_path / MANIFEST_FILENAME, ModelManifest)
        input_schema = load_json_model(bundle_path / SCHEMA_FILENAME, InputSchemaContract)
        metrics = load_json_model(bundle_path / METRICS_FILENAME, MetricsContract)
        threshold = load_json_model(bundle_path / THRESHOLD_FILENAME, ThresholdContract)
        baseline = load_json_model(bundle_path / BASELINE_FILENAME, BaselineProfile)
    except (OSError, UnicodeError, ValueError) as error:
        raise BundleVerificationError(f"strict JSON contract validation failed: {error}") from error
    return manifest, input_schema, metrics, threshold, baseline


def _cross_check_contracts(
    bundle_path: Path,
    manifest: ModelManifest,
    input_schema: InputSchemaContract,
    metrics: MetricsContract,
    threshold: ThresholdContract,
    baseline: BaselineProfile,
) -> None:
    versions = {
        manifest.model_version,
        input_schema.model_version,
        metrics.model_version,
        threshold.model_version,
        baseline.model_version,
    }
    if len(versions) != 1:
        raise BundleVerificationError("cross-file model versions differ")
    if (
        manifest.feature_order != input_schema.feature_order
        or baseline.feature_order != input_schema.feature_order
    ):
        raise BundleVerificationError("cross-file feature order differs")

    for filename in HASHED_BY_MANIFEST_FILENAMES:
        actual_hash = raw_file_hash(bundle_path / filename)
        if manifest.bundle_payload_hashes.get(filename) != actual_hash:
            raise BundleVerificationError(f"manifest payload hash mismatch: {filename}")
    if manifest.lineage.input_schema_hash != raw_file_hash(bundle_path / SCHEMA_FILENAME):
        raise BundleVerificationError("schema lineage hash mismatch")
    if manifest.lineage.baseline_profile_hash != raw_file_hash(bundle_path / BASELINE_FILENAME):
        raise BundleVerificationError("baseline lineage hash mismatch")
    if manifest.lineage.configuration_hash != training_config_hash(manifest.configuration):
        raise BundleVerificationError("configuration lineage hash mismatch")
    split_manifest = manifest.split_manifest
    if manifest.lineage.dataset_hash != split_manifest.dataset_hash:
        raise BundleVerificationError("dataset identity differs from split lineage")
    if manifest.lineage.split_assignment_hash != split_manifest.assignment_hash:
        raise BundleVerificationError("assignment identity differs from split lineage")
    if (
        manifest.calibration_audit.training_membership_hash
        != split_manifest.splits["train"].membership_hash
    ):
        raise BundleVerificationError("calibration membership is not the training split")
    if manifest.calibration_audit.training_row_count != split_manifest.splits["train"].row_count:
        raise BundleVerificationError("calibration support differs from the training split")
    if baseline.training_membership_hash != split_manifest.splits["train"].membership_hash:
        raise BundleVerificationError("baseline membership is not the training split")
    if baseline.training_row_count != split_manifest.splits["train"].row_count:
        raise BundleVerificationError("baseline support differs from training split")
    if metrics.held_out_test.row_count != split_manifest.splits["test"].row_count:
        raise BundleVerificationError("held-out support differs from test split")
    evidence = metrics.validation_threshold_selection
    if evidence.validation_membership_hash != split_manifest.splits["validation"].membership_hash:
        raise BundleVerificationError("threshold evidence is not the validation split")
    if evidence.validation_row_count != split_manifest.splits["validation"].row_count:
        raise BundleVerificationError("threshold evidence support differs from validation split")
    if threshold.validation_row_count != evidence.validation_row_count:
        raise BundleVerificationError("locked threshold support differs from validation evidence")
    if threshold.validation_membership_hash != evidence.validation_membership_hash:
        raise BundleVerificationError("threshold validation membership differs from metrics")
    if threshold.validation_label_score_hash != evidence.validation_label_score_hash:
        raise BundleVerificationError("threshold label/score evidence differs from metrics")
    selected = evidence.selected
    if (
        threshold.threshold != selected.threshold
        or threshold.threshold_numerator != selected.threshold_numerator
        or threshold.selected_false_negatives != selected.false_negatives
        or threshold.selected_false_positives != selected.false_positives
        or threshold.selected_synthetic_cost != selected.synthetic_cost
    ):
        raise BundleVerificationError("locked threshold differs from validation selection")
    if metrics.held_out_test.threshold != threshold.threshold:
        raise BundleVerificationError("test evaluation used a different threshold")
    if baseline.locked_decision_distribution.threshold != threshold.threshold:
        raise BundleVerificationError("baseline decision reference used a different threshold")
    if not (
        manifest.created_at == metrics.created_at == threshold.locked_at == baseline.created_at
    ):
        raise BundleVerificationError("bundle creation/threshold timestamps differ")


def inspect_bundle(bundle_path: Path) -> ValidatedBundleMetadata:
    """Validate structure, bytes, JSON, and identities without loading joblib."""

    _validate_structure(bundle_path)
    _parse_and_verify_checksums(bundle_path)
    manifest, input_schema, metrics, threshold, baseline = _parse_contracts(bundle_path)
    _cross_check_contracts(bundle_path, manifest, input_schema, metrics, threshold, baseline)
    return ValidatedBundleMetadata(
        path=bundle_path,
        identity=BundleIdentity(
            model_version=manifest.model_version,
            manifest_sha256=sha256_file(bundle_path / MANIFEST_FILENAME),
        ),
        manifest=manifest,
        input_schema=input_schema,
        metrics=metrics,
        threshold=threshold,
        baseline=baseline,
    )


def verify_bundle(
    bundle_path: Path,
    *,
    trusted_origin: bool,
    model_loader: ModelLoader = _default_model_loader,
) -> VerifiedBundle:
    """Run ordered verification, then load and smoke-test a trusted-origin joblib."""

    metadata = inspect_bundle(bundle_path)
    if not trusted_origin:
        raise BundleVerificationError(
            "joblib deserialization requires a trusted origin; checksums are not authenticity proof"
        )
    try:
        model = cast(ProbabilityModel, model_loader(bundle_path / MODEL_FILENAME))
        smoke_frame = pd.DataFrame(
            [metadata.input_schema.smoke_example],
            columns=metadata.input_schema.feature_order,
        )
        probabilities = np.asarray(model.predict_proba(smoke_frame), dtype=float)
        classes = np.asarray(model.classes_)
        positive_positions = np.flatnonzero(classes == 1)
        if probabilities.shape != (1, len(classes)) or len(positive_positions) != 1:
            raise ValueError("unexpected smoke prediction shape/classes")
        smoke_score = float(probabilities[0, int(positive_positions[0])])
        if not np.isfinite(smoke_score) or not 0.0 <= smoke_score <= 1.0:
            raise ValueError("smoke prediction is not finite in [0, 1]")
    except (AttributeError, IndexError, TypeError, ValueError) as error:
        raise BundleVerificationError(f"trusted model smoke prediction failed: {error}") from error
    return VerifiedBundle(metadata=metadata, model=model, smoke_score=smoke_score)
