"""Real-bundle stationary, drifted, tiny, labeled, and deterministic report integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import numpy as np
import pandas as pd

from modelguard.core.serialization import canonical_json_bytes
from modelguard.data.generator import generate_synthetic_data
from modelguard.data.schema import FEATURE_ORDER
from modelguard.inference.events import ApprovedSyntheticFeaturesV1, PredictionEventV1
from modelguard.inference.predictor import RiskDecision
from modelguard.monitoring.config import PERFORMANCE_SCOPE_WORDING, MonitoringConfig
from modelguard.monitoring.events import EventIdentity, target_identity_from_bundle
from modelguard.monitoring.performance import DelayedLabelV1
from modelguard.monitoring.service import (
    LocalMonitoringRunSpec,
    MonitoringRunResult,
    run_local_monitoring,
)
from modelguard.monitoring.state import DataQualityState, DriftState, PerformanceState
from modelguard.training.bundle import VerifiedBundle, verify_bundle


def _feature_dict(row: tuple[object, ...]) -> dict[str, object]:
    raw = dict(zip(FEATURE_ORDER, row, strict=True))
    return {
        "amount": float(raw["amount"]),
        "transaction_hour": int(raw["transaction_hour"]),
        "velocity_1h": int(raw["velocity_1h"]),
        "distance_from_home_km": float(raw["distance_from_home_km"]),
        "device_risk_score": float(raw["device_risk_score"]),
        "merchant_risk_score": float(raw["merchant_risk_score"]),
        "is_new_device": bool(raw["is_new_device"]),
        "country_code": str(raw["country_code"]),
        "device_type": str(raw["device_type"]),
    }


def _shift(features: dict[str, object]) -> dict[str, object]:
    return {
        **features,
        "amount": min(25_000.0, float(features["amount"]) * 20 + 5_000),
        "velocity_1h": min(30, int(features["velocity_1h"]) + 15),
        "distance_from_home_km": min(1_000.0, float(features["distance_from_home_km"]) + 400),
        "device_risk_score": min(1.0, 0.8 + float(features["device_risk_score"]) * 0.2),
        "merchant_risk_score": min(1.0, 0.8 + float(features["merchant_risk_score"]) * 0.2),
        "is_new_device": True,
        "country_code": "BR",
        "device_type": "tablet",
    }


def _events(
    bundle: VerifiedBundle,
    *,
    window_end: datetime,
    count: int,
    shifted: bool,
    seed: int = 8_080,
) -> list[PredictionEventV1]:
    dataset = generate_synthetic_data(count, seed=seed)
    feature_rows = [
        _feature_dict(row)
        for row in dataset.loc[:, list(FEATURE_ORDER)].itertuples(index=False, name=None)
    ]
    if shifted:
        feature_rows = [_shift(row) for row in feature_rows]
    frame = pd.DataFrame(feature_rows, columns=FEATURE_ORDER)
    probabilities = np.asarray(bundle.model.predict_proba(frame), dtype=float)
    classes = np.asarray(bundle.model.classes_)
    positive_index = int(np.flatnonzero(classes == 1)[0])
    scores = probabilities[:, positive_index]
    target = target_identity_from_bundle(bundle.metadata)
    threshold = bundle.metadata.threshold.threshold
    start = window_end - timedelta(hours=1)
    scenario = "shifted" if shifted else "stationary"
    events: list[PredictionEventV1] = []
    for index, (features, score) in enumerate(zip(feature_rows, scores, strict=True)):
        event_id = uuid5(
            NAMESPACE_URL,
            f"integration:{scenario}:{window_end.isoformat()}:{index}",
        )
        events.append(
            PredictionEventV1(
                event_schema_version=target.event_schema_version,
                event_id=event_id,
                request_id=uuid5(
                    NAMESPACE_URL,
                    f"integration:request:{scenario}:{window_end.isoformat()}:{index}",
                ),
                event_timestamp=start + timedelta(seconds=(index * 37) % 3_600, microseconds=index),
                model_version=target.model_version,
                bundle_manifest_sha256=target.bundle_manifest_sha256,
                input_schema_version=target.input_schema_version,
                features=ApprovedSyntheticFeaturesV1.model_validate(features),
                score=float(score),
                decision=(
                    RiskDecision.HIGH_RISK if float(score) >= threshold else RiskDecision.LOW_RISK
                ),
                latency_ms=1.0,
            )
        )
    return events


def _write_events(directory: Path, events: list[PredictionEventV1], *, split: bool = False) -> None:
    directory.mkdir(parents=True)
    lines = [canonical_json_bytes(event) + b"\n" for event in events]
    if split:
        midpoint = len(lines) // 2
        (directory / "partition-b.jsonl").write_bytes(b"".join(reversed(lines[midpoint:])))
        (directory / "partition-a.jsonl").write_bytes(b"".join(reversed(lines[:midpoint])))
    else:
        (directory / "events.jsonl").write_bytes(b"".join(lines))


def _run(
    *,
    bundle: VerifiedBundle,
    target: EventIdentity,
    event_directory: Path,
    report_directory: Path,
    window_end: datetime,
    label_directory: Path | None = None,
) -> MonitoringRunResult:
    return run_local_monitoring(
        LocalMonitoringRunSpec(
            bundle_path=bundle.metadata.path,
            event_directory=event_directory,
            report_directory=report_directory,
            target_identity=target,
            label_directory=label_directory,
            window_end=window_end,
            as_of=window_end + timedelta(minutes=10),
        ),
        config=MonitoringConfig(),
    )


def test_stationary_shifted_tiny_unlabeled_and_labeled_windows_are_independent_and_deterministic(
    tmp_path: Path,
    audited_workspace: object,
) -> None:
    bundle = verify_bundle(audited_workspace.result.bundle_path, trusted_origin=True)
    target = target_identity_from_bundle(bundle.metadata)
    event_directory = tmp_path / "events"
    report_directory = tmp_path / "reports"

    first_end = datetime(2026, 1, 1, 1, tzinfo=UTC)
    first_events = _events(bundle, window_end=first_end, count=1_000, shifted=False)
    _write_events(event_directory, first_events)
    first = _run(
        bundle=bundle,
        target=target,
        event_directory=event_directory,
        report_directory=report_directory,
        window_end=first_end,
    )

    second_end = first_end + timedelta(hours=1)
    second_events = _events(
        bundle,
        window_end=second_end,
        count=1_000,
        shifted=False,
        seed=8_081,
    )
    (event_directory / "second.jsonl").write_bytes(
        b"".join(canonical_json_bytes(event) + b"\n" for event in second_events)
    )
    second = _run(
        bundle=bundle,
        target=target,
        event_directory=event_directory,
        report_directory=report_directory,
        window_end=second_end,
    )

    drift_end = second_end + timedelta(hours=1)
    drift_events = _events(bundle, window_end=drift_end, count=1_000, shifted=True)
    (event_directory / "drift.jsonl").write_bytes(
        b"".join(canonical_json_bytes(event) + b"\n" for event in drift_events)
    )
    drifted = _run(
        bundle=bundle,
        target=target,
        event_directory=event_directory,
        report_directory=report_directory,
        window_end=drift_end,
    )

    tiny_end = drift_end + timedelta(hours=1)
    tiny_events = _events(bundle, window_end=tiny_end, count=25, shifted=False)
    (event_directory / "tiny.jsonl").write_bytes(
        b"".join(canonical_json_bytes(event) + b"\n" for event in tiny_events)
    )
    tiny = _run(
        bundle=bundle,
        target=target,
        event_directory=event_directory,
        report_directory=report_directory,
        window_end=tiny_end,
    )

    assert first.report.states.data_quality is DataQualityState.VALID
    assert first.report.states.drift is DriftState.HEALTHY
    assert first.report.states.performance is PerformanceState.UNKNOWN
    assert second.report.states.drift is DriftState.HEALTHY
    assert second.report.records.counts.outside_window == 1_000
    assert drifted.report.states.data_quality is DataQualityState.VALID
    assert drifted.report.states.drift is DriftState.DEGRADED
    assert drifted.report.states.performance is PerformanceState.UNKNOWN
    assert tiny.report.states.data_quality is DataQualityState.INSUFFICIENT_DATA
    assert tiny.report.states.drift is DriftState.UNKNOWN
    assert tiny.report.records.counts.accepted_target == 25

    labeled_end = tiny_end + timedelta(hours=1)
    labeled_events = _events(bundle, window_end=labeled_end, count=1_000, shifted=False)
    (event_directory / "labeled.jsonl").write_bytes(
        b"".join(canonical_json_bytes(event) + b"\n" for event in labeled_events)
    )
    low_risk_ids = {
        event.event_id for event in labeled_events if event.decision is RiskDecision.LOW_RISK
    }
    for event in labeled_events:
        if len(low_risk_ids) >= 20:
            break
        low_risk_ids.add(event.event_id)
    labels = [
        DelayedLabelV1(
            label_schema_version="modelguard.label.v1",
            event_id=event.event_id,
            label=1 if event.event_id in low_risk_ids else 0,
            labeled_at=labeled_end + timedelta(minutes=5),
        )
        for event in labeled_events
    ]
    label_directory = tmp_path / "labels"
    label_directory.mkdir()
    (label_directory / "labels.jsonl").write_bytes(
        b"".join(canonical_json_bytes(label) + b"\n" for label in labels)
    )
    labeled = _run(
        bundle=bundle,
        target=target,
        event_directory=event_directory,
        report_directory=report_directory,
        window_end=labeled_end,
        label_directory=label_directory,
    )
    assert labeled.report.states.drift is DriftState.HEALTHY
    assert labeled.report.states.performance is PerformanceState.DEGRADED
    assert labeled.report.performance.metrics is not None
    assert labeled.report.performance.interpretation == PERFORMANCE_SCOPE_WORDING
    assert labeled.report.performance.metrics.synthetic_cost_delta >= 0.25


def test_report_id_and_checksum_survive_repartition_and_enumeration_order(
    tmp_path: Path,
    audited_workspace: object,
) -> None:
    bundle = verify_bundle(audited_workspace.result.bundle_path, trusted_origin=True)
    target = target_identity_from_bundle(bundle.metadata)
    window_end = datetime(2026, 1, 2, 1, tzinfo=UTC)
    events = _events(bundle, window_end=window_end, count=600, shifted=False)
    single = tmp_path / "single"
    partitioned = tmp_path / "partitioned"
    _write_events(single, events)
    _write_events(partitioned, events, split=True)

    first = _run(
        bundle=bundle,
        target=target,
        event_directory=single,
        report_directory=tmp_path / "reports-a",
        window_end=window_end,
    )
    second = _run(
        bundle=bundle,
        target=target,
        event_directory=partitioned,
        report_directory=tmp_path / "reports-b",
        window_end=window_end,
    )

    assert first.report.report_id == second.report.report_id
    assert first.published.json_sha256 == second.published.json_sha256
    assert first.published.html_sha256 == second.published.html_sha256
