"""Generator and strict data-quality contract tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modelguard.data.generator import dataset_hash, generate_synthetic_data
from modelguard.data.schema import (
    DATASET_COLUMNS,
    GENERATOR_ONLY_COLUMNS,
    InputSchemaContract,
    build_input_schema,
)
from modelguard.data.validation import DataQualityError, validate_dataset


def test_generator_is_deterministic_prefix_stable_and_seed_sensitive() -> None:
    first = generate_synthetic_data(120, seed=41)
    repeated = generate_synthetic_data(120, seed=41)
    longer = generate_synthetic_data(180, seed=41)
    changed_seed = generate_synthetic_data(120, seed=42)

    pd.testing.assert_frame_equal(first, repeated, check_exact=True)
    pd.testing.assert_frame_equal(first, longer.iloc[:120].reset_index(drop=True), check_exact=True)
    assert not first.equals(changed_seed)


def test_generator_persists_stable_unique_ids_and_no_latent_columns() -> None:
    dataset = generate_synthetic_data(300, seed=2026)

    assert list(dataset.columns) == list(DATASET_COLUMNS)
    assert dataset["event_id"].is_unique
    assert dataset["event_id"].str.fullmatch(r"syn-v1-[0-9a-f]{32}").all()
    assert not GENERATOR_ONLY_COLUMNS.intersection(dataset.columns)
    assert set(dataset["is_fraud"]) == {0, 1}


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(columns="amount"), "missing columns"),
        (lambda frame: frame.assign(unexpected=1), "extra columns"),
        (lambda frame: frame.assign(latent_logit=0.1), "generator-only/leaky"),
        (
            lambda frame: frame.assign(
                event_id=[
                    frame.iloc[0]["event_id"],
                    *frame["event_id"].iloc[1:-1],
                    frame.iloc[0]["event_id"],
                ]
            ),
            "duplicate",
        ),
        (lambda frame: frame.assign(amount=np.nan), "missing feature"),
        (lambda frame: frame.assign(amount=np.inf), "finite"),
        (lambda frame: frame.assign(transaction_hour=24), "outside the locked domain"),
        (lambda frame: frame.assign(country_code="ZZ"), "categorical domain"),
        (lambda frame: frame.assign(is_fraud=0), "both classes"),
    ],
)
def test_quality_rejects_malformed_leaky_or_single_class_data(
    mutation: object,
    message: str,
) -> None:
    dataset = generate_synthetic_data(160, seed=99)
    mutated = mutation(dataset.copy())  # type: ignore[operator]

    with pytest.raises(DataQualityError, match=message):
        validate_dataset(mutated)


def test_dataset_hash_is_independent_of_physical_row_order() -> None:
    dataset = generate_synthetic_data(140, seed=21)
    shuffled = dataset.sample(frac=1.0, random_state=12).reset_index(drop=True)

    assert dataset_hash(dataset) == dataset_hash(shuffled)


@pytest.mark.parametrize(
    ("feature", "value", "message"),
    [
        ("amount", 25_000.01, "outside the schema bounds"),
        ("transaction_hour", 2.5, "must be an integer"),
        ("is_new_device", 1, "must be a boolean"),
        ("country_code", "ZZ", "categorical domain"),
    ],
)
def test_input_schema_rejects_invalid_smoke_values(
    feature: str,
    value: object,
    message: str,
) -> None:
    payload = build_input_schema("1.0.0").model_dump(mode="python")
    payload["smoke_example"][feature] = value

    with pytest.raises(ValueError, match=message):
        InputSchemaContract.model_validate(payload)
