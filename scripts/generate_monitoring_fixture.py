#!/usr/bin/env python3
"""Generate deterministic closed-window Phase 05 prediction and optional label fixtures."""

from __future__ import annotations

import argparse
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from modelguard.core.serialization import canonical_json_bytes
from modelguard.data.generator import generate_synthetic_data
from modelguard.data.schema import FEATURE_ORDER
from modelguard.inference.events import ApprovedSyntheticFeaturesV1, PredictionEventV1
from modelguard.inference.predictor import RiskDecision
from modelguard.monitoring.events import parse_utc_timestamp
from modelguard.monitoring.performance import DelayedLabelV1
from modelguard.training.bundle import verify_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("baseline", "drifted", "tiny"), required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--bundle", type=Path, default=Path("artifacts/model-bundles/1.0.0"))
    parser.add_argument("--event-dir", type=Path, default=Path("artifacts/predictions"))
    parser.add_argument("--row-count", type=int)
    parser.add_argument("--label-mode", choices=("none", "generator", "flipped"), default="none")
    parser.add_argument("--label-dir", type=Path, default=Path("artifacts/labels"))
    return parser


def _python_features(row: object) -> dict[str, Any]:
    values = row._asdict()  # type: ignore[attr-defined]
    return {
        "amount": float(values["amount"]),
        "transaction_hour": int(values["transaction_hour"]),
        "velocity_1h": int(values["velocity_1h"]),
        "distance_from_home_km": float(values["distance_from_home_km"]),
        "device_risk_score": float(values["device_risk_score"]),
        "merchant_risk_score": float(values["merchant_risk_score"]),
        "is_new_device": bool(values["is_new_device"]),
        "country_code": str(values["country_code"]),
        "device_type": str(values["device_type"]),
    }


def _shift(features: dict[str, Any]) -> dict[str, Any]:
    shifted = dict(features)
    shifted.update(
        {
            "amount": min(25_000.0, float(features["amount"]) * 20.0 + 5_000.0),
            "velocity_1h": min(30, int(features["velocity_1h"]) + 15),
            "distance_from_home_km": min(1_000.0, float(features["distance_from_home_km"]) + 400.0),
            "device_risk_score": min(1.0, 0.8 + 0.2 * float(features["device_risk_score"])),
            "merchant_risk_score": min(1.0, 0.8 + 0.2 * float(features["merchant_risk_score"])),
            "is_new_device": True,
            "country_code": "BR",
            "device_type": "tablet",
        }
    )
    return shifted


def _create_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise FileExistsError(
                f"fixture path already contains different bytes: {path}"
            ) from None
        return
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("fixture write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    args = _parser().parse_args()
    row_count = (
        args.row_count if args.row_count is not None else (50 if args.scenario == "tiny" else 1_000)
    )
    if row_count <= 0:
        raise ValueError("row-count must be positive")
    window_end = parse_utc_timestamp(args.window_end, name="window_end")
    window_start = window_end - timedelta(hours=1)
    verified = verify_bundle(args.bundle, trusted_origin=True)
    metadata = verified.metadata
    dataset = generate_synthetic_data(row_count, seed=8_080)
    feature_rows = [_python_features(row) for row in dataset.itertuples(index=False)]
    if args.scenario == "drifted":
        feature_rows = [_shift(features) for features in feature_rows]
    feature_models = [ApprovedSyntheticFeaturesV1.model_validate(row) for row in feature_rows]
    frame = dataset.loc[:, list(FEATURE_ORDER)].copy()
    if args.scenario == "drifted":
        for index, feature_model in enumerate(feature_models):
            for name in FEATURE_ORDER:
                frame.at[index, name] = getattr(feature_model, name)
    probabilities = np.asarray(verified.model.predict_proba(frame), dtype=float)
    classes = np.asarray(verified.model.classes_)
    positive_positions = np.flatnonzero(classes == 1)
    if probabilities.shape[0] != row_count or len(positive_positions) != 1:
        raise ValueError("verified model returned an unexpected fixture prediction shape")
    scores = probabilities[:, int(positive_positions[0])]

    event_lines: list[bytes] = []
    labels: list[DelayedLabelV1] = []
    end_key = window_end.strftime("%Y%m%dT%H%M%SZ")
    for index, (features, score) in enumerate(zip(feature_models, scores, strict=True)):
        event_id = uuid5(NAMESPACE_URL, f"modelguard:{args.scenario}:{end_key}:event:{index}")
        timestamp = window_start + timedelta(
            seconds=(index * 37) % 3_600,
            microseconds=index % 1_000_000,
        )
        decision = (
            RiskDecision.HIGH_RISK
            if float(score) >= metadata.threshold.threshold
            else RiskDecision.LOW_RISK
        )
        event = PredictionEventV1(
            event_schema_version="modelguard.prediction-event.v1",
            event_id=event_id,
            request_id=uuid5(
                NAMESPACE_URL, f"modelguard:{args.scenario}:{end_key}:request:{index}"
            ),
            event_timestamp=timestamp,
            model_version=metadata.identity.model_version,
            bundle_manifest_sha256=metadata.identity.manifest_sha256,
            input_schema_version=metadata.input_schema.schema_version,
            features=features,
            score=float(score),
            decision=decision,
            latency_ms=1.0 + (index % 10) / 10,
        )
        event_lines.append(canonical_json_bytes(event) + b"\n")
        if args.label_mode != "none":
            label = int(dataset.iloc[index]["is_fraud"])
            if args.label_mode == "flipped":
                label = 1 - label
            labels.append(
                DelayedLabelV1(
                    label_schema_version="modelguard.label.v1",
                    event_id=event_id,
                    label=label,
                    labeled_at=window_end + timedelta(minutes=5),
                )
            )

    event_path = args.event_dir / f"monitoring-{args.scenario}-{end_key}.jsonl"
    _create_exact(event_path, b"".join(event_lines))
    label_path: Path | None = None
    if labels:
        label_path = args.label_dir / f"labels-{args.scenario}-{end_key}.jsonl"
        _create_exact(label_path, b"".join(canonical_json_bytes(label) + b"\n" for label in labels))
    print(
        json.dumps(
            {
                "event_path": str(event_path),
                "label_path": str(label_path) if label_path is not None else None,
                "manifest_sha256": metadata.identity.manifest_sha256,
                "model_version": metadata.identity.model_version,
                "row_count": row_count,
                "scenario": args.scenario,
                "window_end": args.window_end,
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
