"""Strict dataset schema and quality validation."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from modelguard.data.schema import (
    DATASET_COLUMNS,
    GENERATOR_ONLY_COLUMNS,
    ID_COLUMN,
    LABEL_COLUMN,
    canonical_feature_definitions,
)

EVENT_ID_PATTERN = re.compile(r"^syn-v1-[0-9a-f]{32}$")
QUALITY_CHECKS = (
    "exact_columns_and_order",
    "no_generator_only_or_leakage_columns",
    "non_empty_dataset",
    "stable_non_missing_unique_event_ids",
    "no_missing_values",
    "finite_numeric_values",
    "closed_feature_domains",
    "binary_label_with_both_classes",
)


class DataQualityError(ValueError):
    """Raised with every independently detected dataset violation."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = tuple(violations)
        super().__init__("dataset quality validation failed: " + "; ".join(violations))


@dataclass(frozen=True)
class QualitySummary:
    """Finite facts persisted after a successful validation."""

    row_count: int
    class_counts: dict[str, int]
    missing_counts: dict[str, int]
    checks: tuple[str, ...] = QUALITY_CHECKS


def _numeric_values(
    dataset: pd.DataFrame, column: str, violations: list[str]
) -> NDArray[np.float64] | None:
    try:
        values = np.asarray(pd.to_numeric(dataset[column], errors="raise"), dtype=np.float64)
    except (TypeError, ValueError):
        violations.append(f"{column}: values must be numeric")
        return None
    if not np.isfinite(values).all():
        violations.append(f"{column}: values must be finite")
    return values


def validate_dataset(dataset: pd.DataFrame) -> QualitySummary:
    """Validate the exact training dataset contract and return audit facts."""

    violations: list[str] = []
    actual_columns = list(dataset.columns)
    expected_columns = list(DATASET_COLUMNS)
    missing_columns = [column for column in expected_columns if column not in actual_columns]
    extra_columns = [column for column in actual_columns if column not in expected_columns]
    leaked_columns = sorted(GENERATOR_ONLY_COLUMNS.intersection(extra_columns))
    if missing_columns:
        violations.append(f"missing columns: {missing_columns}")
    if extra_columns:
        violations.append(f"extra columns: {extra_columns}")
    if leaked_columns:
        violations.append(f"generator-only/leaky columns: {leaked_columns}")
    if not missing_columns and not extra_columns and actual_columns != expected_columns:
        violations.append("columns are not in the locked canonical order")
    if dataset.empty:
        violations.append("dataset must contain at least one row")

    if ID_COLUMN in dataset:
        event_ids = dataset[ID_COLUMN]
        if event_ids.isna().any():
            violations.append("event_id: missing values are forbidden")
        else:
            event_id_strings = event_ids.astype(str)
            if (event_id_strings.str.len() == 0).any():
                violations.append("event_id: empty values are forbidden")
            if not event_id_strings.map(
                lambda value: bool(EVENT_ID_PATTERN.fullmatch(value))
            ).all():
                violations.append("event_id: values must use the stable synthetic ID format")
        if event_ids.duplicated().any():
            violations.append("event_id: duplicate values are forbidden")

    missing_counts = {
        column: int(dataset[column].isna().sum())
        for column in expected_columns
        if column in dataset
    }
    if any(missing_counts.values()):
        violations.append("missing feature or label values are forbidden")

    definitions = {definition.name: definition for definition in canonical_feature_definitions()}
    for column, definition in definitions.items():
        if column not in dataset:
            continue
        if definition.data_type in {"float", "integer"}:
            values = _numeric_values(dataset, column, violations)
            if values is None or not np.isfinite(values).all():
                continue
            minimum = definition.minimum
            maximum = definition.maximum
            if minimum is None or maximum is None:
                raise RuntimeError(f"internal numeric schema is missing bounds for {column}")
            if ((values < minimum) | (values > maximum)).any():
                violations.append(f"{column}: values are outside the locked domain")
            if definition.data_type == "integer" and not np.equal(values, np.floor(values)).all():
                violations.append(f"{column}: values must be integers")
        elif definition.data_type == "boolean":
            valid_boolean = dataset[column].map(lambda value: isinstance(value, (bool, np.bool_)))
            if not valid_boolean.all():
                violations.append(f"{column}: values must be booleans")
        else:
            categories = definition.categories
            if categories is None:
                raise RuntimeError(f"internal categorical schema is missing a domain for {column}")
            invalid = ~dataset[column].isin(categories)
            if invalid.any():
                violations.append(f"{column}: values are outside the locked categorical domain")

    class_counts: dict[str, int] = {}
    if LABEL_COLUMN in dataset:
        label_values = _numeric_values(dataset, LABEL_COLUMN, violations)
        if label_values is not None and np.isfinite(label_values).all():
            unique_labels = set(label_values.tolist())
            if not unique_labels.issubset({0.0, 1.0}):
                violations.append("is_fraud: label must be binary 0/1")
            else:
                class_counts = {
                    "0": int((label_values == 0.0).sum()),
                    "1": int((label_values == 1.0).sum()),
                }
                if set(unique_labels) != {0.0, 1.0}:
                    violations.append("is_fraud: both classes must be present")

    if violations:
        raise DataQualityError(violations)
    return QualitySummary(
        row_count=len(dataset),
        class_counts=class_counts,
        missing_counts=missing_counts,
    )
