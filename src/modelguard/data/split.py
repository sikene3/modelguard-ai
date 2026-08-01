"""Canonical persisted train/validation/test split assignments."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import Field, model_validator
from sklearn.model_selection import train_test_split

from modelguard.core.hashing import HashRecord, canonical_json_hash
from modelguard.core.serialization import StrictArtifactModel
from modelguard.data.generator import dataset_hash
from modelguard.data.schema import ID_COLUMN, LABEL_COLUMN
from modelguard.training.config import SplitConfig

SplitName = Literal["train", "validation", "test"]
SPLIT_NAMES: tuple[SplitName, ...] = ("train", "validation", "test")
ASSIGNMENT_COLUMNS = (ID_COLUMN, "split")


class SplitSummary(StrictArtifactModel):
    """Support and membership identity for one split."""

    row_count: int = Field(gt=0)
    class_counts: dict[str, int]
    membership_hash: HashRecord

    @model_validator(mode="after")
    def validate_support(self) -> SplitSummary:
        if set(self.class_counts) != {"0", "1"}:
            raise ValueError("split class counts must contain exactly binary labels 0 and 1")
        if any(count <= 0 for count in self.class_counts.values()):
            raise ValueError("each split must contain both classes")
        if sum(self.class_counts.values()) != self.row_count:
            raise ValueError("split class counts must reconcile to row count")
        return self


class SplitManifest(StrictArtifactModel):
    """Auditable identity of the one canonical pre-fit assignment."""

    contract_version: Literal["modelguard.split-manifest.v1"] = "modelguard.split-manifest.v1"
    created_at: str
    strategy: Literal["canonical_stratified_train_validation_test"]
    dataset_hash: HashRecord
    assignment_hash: HashRecord
    train_fraction: float
    validation_fraction: float
    test_fraction: float
    train_remainder_seed: int
    validation_test_seed: int
    splits: dict[SplitName, SplitSummary]

    @model_validator(mode="after")
    def validate_manifest_shape(self) -> SplitManifest:
        if set(self.splits) != set(SPLIT_NAMES):
            raise ValueError("split manifest must contain exactly train, validation, and test")
        total = self.train_fraction + self.validation_fraction + self.test_fraction
        if abs(total - 1.0) > 1e-12:
            raise ValueError("split manifest fractions must sum to one within 1e-12")
        return self


class SplitValidationError(ValueError):
    """Raised before fitting when persisted split evidence is inconsistent."""


def membership_hash(event_ids: list[str]) -> HashRecord:
    """Hash a split membership independent of physical assignment row order."""

    return canonical_json_hash(
        sorted(event_ids),
        ordering="event_id lexicographic ascending",
        exclusions=["assignment row order", "features", "labels", "other split memberships"],
    )


def assignment_hash(assignments: pd.DataFrame) -> HashRecord:
    """Hash the complete ID-to-split mapping in canonical ID order."""

    ordered = assignments.loc[:, ASSIGNMENT_COLUMNS].sort_values(ID_COLUMN, kind="mergesort")
    records = [
        {ID_COLUMN: str(event_id), "split": str(split)}
        for event_id, split in ordered.itertuples(index=False, name=None)
    ]
    return canonical_json_hash(
        records,
        ordering="event_id ascending; fields ordered as event_id then split",
        exclusions=["assignment row order", "dataset features", "dataset labels", "timestamps"],
    )


def create_split_assignments(dataset: pd.DataFrame, config: SplitConfig) -> pd.DataFrame:
    """Create the sole deterministic stratified assignment before any estimator fit."""

    canonical = dataset.sort_values(ID_COLUMN, kind="mergesort")
    event_ids = canonical[ID_COLUMN].astype(str).to_numpy()
    labels = canonical[LABEL_COLUMN].astype(int).to_numpy()
    train_ids, remainder_ids, _, remainder_labels = train_test_split(
        event_ids,
        labels,
        train_size=config.train_fraction,
        random_state=config.train_remainder_seed,
        shuffle=True,
        stratify=labels,
    )
    validation_share = config.validation_fraction / (
        config.validation_fraction + config.test_fraction
    )
    validation_ids, test_ids = train_test_split(
        remainder_ids,
        train_size=validation_share,
        random_state=config.validation_test_seed,
        shuffle=True,
        stratify=remainder_labels,
    )
    records = [
        *({ID_COLUMN: str(event_id), "split": "train"} for event_id in train_ids),
        *({ID_COLUMN: str(event_id), "split": "validation"} for event_id in validation_ids),
        *({ID_COLUMN: str(event_id), "split": "test"} for event_id in test_ids),
    ]
    return pd.DataFrame.from_records(records, columns=ASSIGNMENT_COLUMNS).sort_values(
        ID_COLUMN, kind="mergesort", ignore_index=True
    )


def build_split_manifest(
    dataset: pd.DataFrame,
    assignments: pd.DataFrame,
    config: SplitConfig,
    *,
    created_at: str,
) -> SplitManifest:
    """Build support and canonical hashes for a validated assignment."""

    indexed = dataset.set_index(ID_COLUMN, drop=False)
    summaries: dict[SplitName, SplitSummary] = {}
    for split_name in SPLIT_NAMES:
        ids = assignments.loc[assignments["split"] == split_name, ID_COLUMN].astype(str).tolist()
        labels = indexed.loc[ids, LABEL_COLUMN].astype(int)
        summaries[split_name] = SplitSummary(
            row_count=len(ids),
            class_counts={"0": int((labels == 0).sum()), "1": int((labels == 1).sum())},
            membership_hash=membership_hash(ids),
        )
    return SplitManifest(
        created_at=created_at,
        strategy=config.strategy,
        dataset_hash=dataset_hash(dataset),
        assignment_hash=assignment_hash(assignments),
        train_fraction=config.train_fraction,
        validation_fraction=config.validation_fraction,
        test_fraction=config.test_fraction,
        train_remainder_seed=config.train_remainder_seed,
        validation_test_seed=config.validation_test_seed,
        splits=summaries,
    )


def write_split_assignments(path: Path, assignments: pd.DataFrame) -> None:
    """Persist the canonical mapping with stable physical ordering."""

    path.parent.mkdir(parents=True, exist_ok=True)
    assignments.loc[:, ASSIGNMENT_COLUMNS].sort_values(ID_COLUMN, kind="mergesort").to_csv(
        path,
        index=False,
        lineterminator="\n",
    )


def read_split_assignments(path: Path) -> pd.DataFrame:
    """Load split assignments without inference of synthetic IDs."""

    return pd.read_csv(path, dtype={ID_COLUMN: "string", "split": "string"})


def verify_split_assignments(
    dataset: pd.DataFrame,
    assignments: pd.DataFrame,
    manifest: SplitManifest,
) -> None:
    """Block training unless split lineage, support, and membership all reconcile."""

    violations: list[str] = []
    if list(assignments.columns) != list(ASSIGNMENT_COLUMNS):
        violations.append("assignment columns must be exactly event_id, split")
    elif assignments.isna().any().any():
        violations.append("split assignments cannot contain missing values")
    else:
        if assignments[ID_COLUMN].duplicated().any():
            violations.append("split assignments contain duplicate event IDs")
        unknown_splits = sorted(set(assignments["split"].astype(str)) - set(SPLIT_NAMES))
        if unknown_splits:
            violations.append(f"unknown split names: {unknown_splits}")
        dataset_ids = set(dataset[ID_COLUMN].astype(str))
        assignment_ids = set(assignments[ID_COLUMN].astype(str))
        if dataset_ids != assignment_ids:
            missing = len(dataset_ids - assignment_ids)
            extra = len(assignment_ids - dataset_ids)
            violations.append(
                f"split assignment is not exhaustive/exact (missing={missing}, extra={extra})"
            )

    current_dataset_hash = dataset_hash(dataset)
    if current_dataset_hash != manifest.dataset_hash:
        violations.append("dataset hash does not match persisted split lineage")
    if assignment_hash(assignments) != manifest.assignment_hash:
        violations.append("assignment hash mismatch")

    indexed = dataset.set_index(ID_COLUMN, drop=False)
    for split_name in SPLIT_NAMES:
        ids = assignments.loc[assignments["split"] == split_name, ID_COLUMN].astype(str).tolist()
        expected = manifest.splits.get(split_name)
        if expected is None:
            violations.append(f"missing manifest summary for split {split_name}")
            continue
        if not ids:
            violations.append(f"split {split_name} is empty")
            continue
        if membership_hash(ids) != expected.membership_hash:
            violations.append(f"membership hash mismatch for split {split_name}")
        if len(ids) != expected.row_count:
            violations.append(f"row count mismatch for split {split_name}")
        if set(ids).issubset(indexed.index):
            labels = indexed.loc[ids, LABEL_COLUMN].astype(int)
            counts = {"0": int((labels == 0).sum()), "1": int((labels == 1).sum())}
            if 0 in counts.values():
                violations.append(f"split {split_name} must contain both classes")
            if counts != expected.class_counts:
                violations.append(f"class counts mismatch for split {split_name}")

    if violations:
        raise SplitValidationError("; ".join(violations))
