"""Prefix-stable independent synthetic fraud row generation."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from modelguard.core.hashing import HashRecord, canonical_json_hash
from modelguard.data.schema import (
    COUNTRY_CODES,
    DATASET_COLUMNS,
    DEVICE_TYPES,
    GENERATOR_ONLY_COLUMNS,
    ID_COLUMN,
)

GENERATOR_VERSION: Literal["modelguard.synthetic-independent.v1"] = (
    "modelguard.synthetic-independent.v1"
)


def _event_id(seed: int, row_index: int) -> str:
    identity = f"{GENERATOR_VERSION}:{seed}:{row_index}".encode()
    return f"syn-v1-{hashlib.sha256(identity).hexdigest()[:32]}"


def _generate_row(seed: int, row_index: int) -> dict[str, object]:
    rng = np.random.default_rng(np.random.SeedSequence([seed, row_index]))
    amount = float(np.clip(rng.lognormal(mean=4.4, sigma=1.05), 0.01, 25_000.0))
    transaction_hour = int(rng.integers(0, 24))
    velocity = int(min(rng.poisson(2.1) + (rng.integers(4, 15) if rng.random() < 0.035 else 0), 30))
    distance = float(np.clip(rng.gamma(shape=1.8, scale=38.0), 0.0, 1_000.0))
    device_risk = float(rng.beta(2.0, 4.5))
    merchant_risk = float(rng.beta(2.2, 4.0))
    is_new_device = bool(rng.random() < 0.19)
    country_code = str(rng.choice(COUNTRY_CODES, p=(0.10, 0.12, 0.28, 0.12, 0.16, 0.22)))
    device_type = str(rng.choice(DEVICE_TYPES, p=(0.26, 0.64, 0.10)))

    country_effect = {"BR": 0.40, "DE": -0.15, "EG": 0.20, "GB": -0.10, "IN": 0.32, "US": 0.0}
    device_effect = {"desktop": -0.05, "mobile": 0.12, "tablet": 0.20}
    night_effect = 0.65 if transaction_hour < 6 else 0.0
    latent_logit = (
        -5.20
        + 0.30 * math.log1p(amount)
        + 0.16 * velocity
        + 0.0025 * distance
        + 2.10 * device_risk
        + 1.65 * merchant_risk
        + 0.85 * float(is_new_device)
        + night_effect
        + country_effect[country_code]
        + device_effect[device_type]
    )
    latent_probability = 1.0 / (1.0 + math.exp(-latent_logit))
    is_fraud = int(rng.random() < latent_probability)

    return {
        "event_id": _event_id(seed, row_index),
        "amount": amount,
        "transaction_hour": transaction_hour,
        "velocity_1h": velocity,
        "distance_from_home_km": distance,
        "device_risk_score": device_risk,
        "merchant_risk_score": merchant_risk,
        "is_new_device": is_new_device,
        "country_code": country_code,
        "device_type": device_type,
        "is_fraud": is_fraud,
    }


def generate_synthetic_data(row_count: int, seed: int) -> pd.DataFrame:
    """Generate independent rows; each row depends only on ``seed`` and its index."""

    if row_count <= 0:
        raise ValueError("row_count must be positive")
    rows = [_generate_row(seed, row_index) for row_index in range(row_count)]
    dataset = pd.DataFrame.from_records(rows, columns=DATASET_COLUMNS)
    if GENERATOR_ONLY_COLUMNS.intersection(dataset.columns):
        raise AssertionError("generator-only latent values must never be persisted")
    return dataset


def write_dataset(path: Path, dataset: pd.DataFrame) -> None:
    """Persist the canonical dataset with a deterministic column and float encoding."""

    path.parent.mkdir(parents=True, exist_ok=True)
    dataset.loc[:, DATASET_COLUMNS].to_csv(
        path,
        index=False,
        lineterminator="\n",
        float_format="%.17g",
    )


def read_dataset(path: Path) -> pd.DataFrame:
    """Read the persisted CSV using the canonical logical dtypes."""

    return pd.read_csv(
        path,
        dtype={
            ID_COLUMN: "string",
            "country_code": "string",
            "device_type": "string",
        },
        true_values=["True"],
        false_values=["False"],
    )


def _canonical_scalar(value: object) -> object:
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    return str(value)


def dataset_hash(dataset: pd.DataFrame) -> HashRecord:
    """Hash row content independent of physical row ordering."""

    ordered = dataset.loc[:, DATASET_COLUMNS].sort_values(ID_COLUMN, kind="mergesort")
    records = [
        {
            column: _canonical_scalar(value)
            for column, value in zip(DATASET_COLUMNS, row, strict=True)
        }
        for row in ordered.itertuples(index=False, name=None)
    ]
    return canonical_json_hash(
        records,
        ordering="rows by event_id ascending; columns in locked DATASET_COLUMNS order",
        exclusions=[
            "physical row order",
            "CSV formatting",
            "split assignment",
            "manifest timestamps",
            *sorted(GENERATOR_ONLY_COLUMNS),
        ],
    )
