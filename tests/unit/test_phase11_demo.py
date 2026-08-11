"""Focused tests for the Phase 11 deterministic demo evidence harness."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts.phase11_demo import (
    DemoEvidenceError,
    LocalModelPointer,
    _exercise_sink_outage_async,
    _stable_run_projection,
    build_demo_windows,
)

from modelguard.monitoring.config import MonitoringConfig
from modelguard.training.bundle import BundleIdentity


def test_phase11_windows_are_explicit_adjacent_and_finalized() -> None:
    anchor = datetime(2026, 8, 11, 19, 20, tzinfo=UTC)
    config = MonitoringConfig(finalization_grace_seconds=600)

    insufficient, baseline, drifted = build_demo_windows(anchor, config)

    assert [window.scenario for window in (insufficient, baseline, drifted)] == [
        "insufficient",
        "baseline",
        "drifted",
    ]
    assert insufficient.start == datetime(2026, 8, 11, 16, 20, tzinfo=UTC)
    assert insufficient.end == baseline.start
    assert baseline.end == drifted.start
    assert drifted.end == anchor
    assert all(
        window.as_of == window.end + timedelta(minutes=10)
        for window in (insufficient, baseline, drifted)
    )


def test_phase11_window_builder_rejects_non_utc_anchor() -> None:
    with pytest.raises(ValueError, match="anchor must be expressed in UTC"):
        build_demo_windows(datetime(2026, 8, 11, 19, 20), MonitoringConfig())


def test_local_promotion_pointer_preserves_distinct_active_and_previous_identities() -> None:
    previous = BundleIdentity(model_version="1.0.0", manifest_sha256="a" * 64)
    active = BundleIdentity(model_version="1.0.1", manifest_sha256="b" * 64)

    pointer = LocalModelPointer(
        active=active,
        previous=previous,
        active_bundle_path="artifacts/phase-11-evidence/run/recovery/1.0.1",
        promoted_at="2026-08-11T19:20:00Z",
    )

    assert pointer.active.model_version == "1.0.1"
    assert pointer.previous == previous
    assert pointer.scope == "local_demo_only"


def test_event_sink_outage_is_observable_and_does_not_fail_prediction(
    audited_workspace: Any,
) -> None:
    bundle = Path(audited_workspace.result.bundle_path)

    evidence = asyncio.run(_exercise_sink_outage_async(bundle))

    assert evidence["service_ready_status"] == 200
    assert evidence["prediction_status"] == 200
    assert evidence["classification"] == "operational_event_sink_outage"
    assert evidence["model_degradation_claimed"] is False
    assert evidence["drift_evaluated"] is False
    assert evidence["performance_evaluated"] is False
    assert evidence["sink_closed"] is True


def test_repeatability_projection_excludes_expected_runtime_nondeterminism() -> None:
    def summary(*, run_id: str, duration: float, candidate_manifest: str) -> dict[str, object]:
        report = {
            "window": {"start": "a", "end": "b", "as_of": "b"},
            "states": {
                "run": "succeeded",
                "data_quality": "valid",
                "drift": "healthy",
                "performance": "unknown",
            },
            "records": {"raw": 1000, "accepted_target": 1000},
            "samples": {"minimum_accepted": 500, "accepted": 1000, "headroom": 500},
            "report": {"report_id": "a" * 64, "json_sha256": "b" * 64},
        }
        drifted = {
            **report,
            "states": {**report["states"], "drift": "degraded"},
            "expected_breached_metrics": [{"name": "amount", "state": "degraded"}],
        }
        insufficient = {
            **report,
            "states": {
                **report["states"],
                "data_quality": "insufficient_data",
                "drift": "unknown",
            },
        }
        return {
            "status": "passed",
            "run_id": run_id,
            "duration_seconds": duration,
            "anchor": "2026-08-11T19:20:00Z",
            "model_bundle": {"model_version": "1.0.0", "manifest_sha256": "c" * 64},
            "monitoring_config": {"minimum_accepted_events": 500},
            "healthy_to_degraded": {
                "baseline": report,
                "drifted": drifted,
                "alert": {
                    "transition": "drift=healthy -> drift=degraded",
                    "send_status": "not_configured",
                    "marker_sha256": "f" * 64,
                },
                "dashboard_transition": [
                    {
                        "scenario": "healthy",
                        "states": report["states"],
                        "report_id": "a" * 64,
                        "active_identity": {"model_version": "1.0.0"},
                        "report_target_identity": {"model_version": "1.0.0"},
                        "active_matches_report_target": True,
                        "app_test": {"exceptions": 0},
                        "image": {"sha256": "1" * 64},
                    },
                    {
                        "scenario": "degraded",
                        "states": drifted["states"],
                        "report_id": "2" * 64,
                        "active_identity": {"model_version": "1.0.0"},
                        "report_target_identity": {"model_version": "1.0.0"},
                        "active_matches_report_target": True,
                        "app_test": {"exceptions": 0},
                        "image": {"sha256": "3" * 64},
                    },
                ],
            },
            "insufficient_data": insufficient,
            "event_sink_outage": {
                "prediction_status": 200,
                "classification": "operational_event_sink_outage",
                "model_degradation_claimed": False,
            },
            "controlled_recovery": {
                "candidate_verification": {"manifest_sha256": candidate_manifest}
            },
            "claims": {"accuracy_decrease_claimed": False},
            "teardown": {"status": "verified"},
        }

    first = summary(run_id="local-01", duration=1.0, candidate_manifest="d" * 64)
    second = summary(run_id="local-02", duration=2.0, candidate_manifest="e" * 64)

    assert _stable_run_projection(first) == _stable_run_projection(second)


def test_repeatability_projection_requires_all_evidence_sections() -> None:
    with pytest.raises((KeyError, DemoEvidenceError)):
        _stable_run_projection({"status": "passed"})
