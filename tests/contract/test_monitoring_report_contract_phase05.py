"""Portable JSON Schema parity and strict generated-report validation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from modelguard.core.serialization import canonical_json_bytes, load_strict_json
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.events import EventIdentity
from modelguard.monitoring.report import (
    MONITORING_REPORT_SCHEMA_VERSION,
    MonitoringReport,
    monitoring_report_json_schema,
)
from modelguard.monitoring.service import LocalMonitoringRunSpec, run_local_monitoring
from modelguard.training.bundle import ValidatedBundleMetadata


def test_checked_in_report_schema_matches_model_and_validates_a_real_report(
    tmp_path: Path,
    repository_root: Path,
    monitoring_event_factory: Any,
    monitoring_target: EventIdentity,
    monitoring_metadata: ValidatedBundleMetadata,
) -> None:
    schema_path = repository_root / "contracts" / "monitoring-report-v1.schema.json"
    schema = load_strict_json(schema_path)
    assert schema == monitoring_report_json_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    window_end = datetime(2026, 1, 1, 1, tzinfo=UTC)
    event_directory = tmp_path / "events"
    event_directory.mkdir()
    event = monitoring_event_factory(1, window_end - timedelta(minutes=30))
    (event_directory / "events.jsonl").write_bytes(canonical_json_bytes(event) + b"\n")
    result = run_local_monitoring(
        LocalMonitoringRunSpec(
            bundle_path=monitoring_metadata.path,
            event_directory=event_directory,
            report_directory=tmp_path / "reports",
            target_identity=monitoring_target,
            window_end=window_end,
            as_of=window_end + timedelta(minutes=10),
        ),
        config=MonitoringConfig(minimum_accepted_events=1),
    )
    payload = json.loads(result.published.json_path.read_text())

    validator.validate(payload)
    assert MonitoringReport.model_validate(payload) == result.report
    assert payload["report_schema_version"] == MONITORING_REPORT_SCHEMA_VERSION
    assert set(payload["states"]) == {"run", "data_quality", "drift", "performance"}
    assert "overall_state" not in payload
    assert payload["window"]["delivery_lateness_metric"] == "not_claimed"
    assert payload["records"]["counts"]["raw"] == sum(
        payload["records"]["counts"][name]
        for name in (
            "rejected",
            "outside_window",
            "known_non_target",
            "duplicate",
            "accepted_target",
        )
    )

    malformed = {**payload, "unexpected": "forbidden"}
    with pytest.raises(ValidationError):
        validator.validate(malformed)
