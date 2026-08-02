#!/usr/bin/env python3
"""Validate and summarize machine-readable Phase 07 local-container evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from modelguard.core.serialization import load_strict_json
from modelguard.monitoring.report import MonitoringReport


class EvidenceError(ValueError):
    """One evidence artifact did not prove its declared scenario."""


def _json(path: Path) -> Any:
    try:
        return load_strict_json(path)
    except (OSError, UnicodeError, ValueError) as error:
        raise EvidenceError(f"invalid JSON evidence: {path.name}") from error


def _object(path: Path) -> dict[str, Any]:
    value = _json(path)
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON evidence root must be an object: {path.name}")
    return value


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvidenceError(f"invalid text evidence: {path.name}") from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65_536), b""):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceError(f"unreadable evidence: {path.name}") from error
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise EvidenceError("summary path must be a regular non-symlink file")
    payload = json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _scenario_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("scenario")
    parser.add_argument("--traffic", type=Path, required=True)
    parser.add_argument("--monitor", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-scenario", required=True)
    parser.add_argument("--expected-traffic", type=int)
    parser.add_argument("--expected-accepted", type=int, required=True)
    parser.add_argument("--expected-quality", required=True)
    parser.add_argument("--expected-drift", required=True)
    parser.add_argument("--summary", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _scenario_parser(subparsers)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--evidence-dir", type=Path, required=True)
    smoke.add_argument("--traffic-events", type=int, required=True)
    smoke.add_argument("--expected-source-revision", required=True)
    smoke.add_argument("--summary", type=Path, required=True)

    corrupt = subparsers.add_parser("corrupt-bundle")
    corrupt.add_argument("--evidence-dir", type=Path, required=True)
    corrupt.add_argument("--summary", type=Path, required=True)

    sink = subparsers.add_parser("sink-outage")
    sink.add_argument("--evidence-dir", type=Path, required=True)
    sink.add_argument("--summary", type=Path, required=True)

    demo = subparsers.add_parser("demo")
    demo.add_argument("--healthy-summary", type=Path, required=True)
    demo.add_argument("--drifted-summary", type=Path, required=True)
    demo.add_argument("--dashboard-health", type=Path, required=True)
    demo.add_argument("--summary", type=Path, required=True)

    e2e = subparsers.add_parser("e2e")
    e2e.add_argument("--insufficient-summary", type=Path, required=True)
    e2e.add_argument("--corrupt-summary", type=Path, required=True)
    e2e.add_argument("--sink-summary", type=Path, required=True)
    e2e.add_argument("--summary", type=Path, required=True)
    return parser


def validate_scenario(
    *,
    traffic_path: Path,
    monitor_path: Path,
    report_path: Path,
    expected_scenario: str,
    expected_accepted: int,
    expected_quality: str,
    expected_drift: str,
    expected_traffic: int | None = None,
) -> dict[str, Any]:
    traffic = _object(traffic_path)
    monitor = _object(monitor_path)
    report = MonitoringReport.model_validate_json(report_path.read_bytes())
    _require(traffic.get("status") == "passed", "traffic did not pass")
    _require(traffic.get("scenario") == expected_scenario, "traffic scenario did not match")
    expected_traffic_count = expected_accepted if expected_traffic is None else expected_traffic
    _require(
        traffic.get("successes") == expected_traffic_count,
        "traffic success count did not match",
    )
    _require(traffic.get("failures") == 0, "traffic contained failures")
    _require(monitor.get("run_state") == "succeeded", "monitor run did not succeed")
    _require(
        monitor.get("accepted_target") == expected_accepted,
        "monitor accepted count did not match",
    )
    _require(
        monitor.get("data_quality_state") == expected_quality,
        "monitor quality state did not match",
    )
    _require(monitor.get("drift_state") == expected_drift, "monitor drift state did not match")
    counts = report.records.counts
    _require(counts.raw == expected_accepted, "raw report count did not match")
    _require(counts.accepted_target == expected_accepted, "report accepted count did not match")
    _require(counts.rejected == 0, "scenario report contained rejected events")
    _require(counts.outside_window == 0, "scenario report contained outside-window events")
    _require(counts.known_non_target == 0, "scenario report contained non-target events")
    _require(counts.duplicate == 0, "scenario report contained duplicate events")
    _require(report.states.data_quality.value == expected_quality, "report quality did not match")
    _require(report.states.drift.value == expected_drift, "report drift did not match")
    _require(report.states.performance.value == "unknown", "unlabeled performance was not unknown")
    _require(report.report_id == monitor.get("report_id"), "monitor/report IDs did not match")
    _require(_sha256(report_path) == monitor.get("json_sha256"), "monitor JSON hash did not match")
    return {
        "schema_version": "modelguard.local-scenario-summary.v1",
        "status": "passed",
        "scenario": expected_scenario,
        "states": {
            "run": report.states.run.value,
            "data_quality": report.states.data_quality.value,
            "drift": report.states.drift.value,
            "performance": report.states.performance.value,
        },
        "accepted_target": counts.accepted_target,
        "report_id": report.report_id,
        "artifacts": {
            traffic_path.name: _sha256(traffic_path),
            monitor_path.name: _sha256(monitor_path),
            report_path.name: _sha256(report_path),
        },
    }


def _validate_images(
    evidence_directory: Path,
    *,
    expected_source_revision: str,
) -> dict[str, Any]:
    images = _json(evidence_directory / "images.json")
    _require(isinstance(images, list) and len(images) == 3, "three image inspections are required")
    expected_lock = _sha256(Path("uv.lock"))
    components: list[str] = []
    for image in images:
        _require(isinstance(image, dict), "an image inspection is not an object")
        config = image.get("Config", {})
        _require(isinstance(config, dict), "an image configuration is not an object")
        user = str(config.get("User", ""))
        _require(user == "10001:10001", "an image runtime user is not 10001:10001")
        healthcheck = config.get("Healthcheck", {})
        _require(isinstance(healthcheck, dict), "an image health check is not an object")
        health = healthcheck.get("Test")
        _require(isinstance(health, list) and len(health) >= 2, "an image lacks a health check")
        labels = config.get("Labels", {})
        _require(isinstance(labels, dict), "image labels are not an object")
        component = labels.get("io.modelguard.component")
        _require(component in {"api", "dashboard", "monitor"}, "image component label is invalid")
        _require(
            labels.get("io.modelguard.uv-lock.sha256") == expected_lock,
            "image lock label does not match uv.lock",
        )
        revision = labels.get("org.opencontainers.image.revision")
        _require(
            revision == expected_source_revision,
            "image revision label does not match the current worktree",
        )
        components.append(component)
    _require(set(components) == {"api", "dashboard", "monitor"}, "image set is incomplete")
    return {"components": sorted(components), "uv_lock_sha256": expected_lock}


def validate_smoke(
    evidence_directory: Path,
    *,
    traffic_events: int,
    expected_source_revision: str,
) -> dict[str, Any]:
    live = _object(evidence_directory / "api-live.json")
    ready = _object(evidence_directory / "api-ready.json")
    version = _object(evidence_directory / "api-version.json")
    prediction = _object(evidence_directory / "prediction.json")
    _require(live == {"status": "live"}, "API liveness evidence failed")
    _require(ready == {"status": "ready"}, "API readiness evidence failed")
    _require(version.get("model_ready") is True, "API version did not prove a ready model")
    _require(
        set(prediction) == {"request_id", "risk_score", "decision", "model_version", "latency_ms"},
        "prediction contract evidence failed",
    )
    metrics = _text(evidence_directory / "api-metrics.prom")
    persisted = traffic_events + 1
    _require(
        f'modelguard_event_sink_operations_total{{outcome="local_persisted"}} {persisted}.0'
        in metrics,
        "event persistence metric did not match prediction traffic",
    )
    _require(
        _text(evidence_directory / "dashboard-health.txt").strip() == "ok",
        "dashboard health failed",
    )
    _require((evidence_directory / "dashboard.html").stat().st_size > 0, "dashboard root was empty")
    offline_html = evidence_directory / "monitor-report.html"
    _require(offline_html.stat().st_size > 0, "offline monitor HTML was empty")
    monitor = _object(evidence_directory / "monitor.json")
    _require(
        _sha256(offline_html) == monitor.get("html_sha256"),
        "monitor HTML hash did not match",
    )
    image_files = _object(evidence_directory / "image-files.json")
    _require(
        image_files == {"api": "clean", "dashboard": "clean", "monitor": "clean"},
        "an image contained a forbidden baked artifact",
    )
    scenario = validate_scenario(
        traffic_path=evidence_directory / "traffic.json",
        monitor_path=evidence_directory / "monitor.json",
        report_path=evidence_directory / "latest-report.json",
        expected_scenario="baseline",
        expected_accepted=persisted,
        expected_traffic=traffic_events,
        expected_quality="valid",
        expected_drift="healthy",
    )
    image_summary = _validate_images(
        evidence_directory,
        expected_source_revision=expected_source_revision,
    )
    return {
        "schema_version": "modelguard.local-smoke-summary.v1",
        "status": "passed",
        "health": {"api_live": "live", "api_ready": "ready", "dashboard": "ok"},
        "prediction_model_version": prediction["model_version"],
        "event_persistence_count": persisted,
        "scenario": scenario,
        "images": image_summary,
    }


def _status(path: Path) -> int:
    try:
        return int(_text(path).strip())
    except ValueError as error:
        raise EvidenceError(f"invalid HTTP status evidence: {path.name}") from error


def validate_corrupt_bundle(evidence_directory: Path) -> dict[str, Any]:
    _require(_status(evidence_directory / "live.status") == 200, "corrupt API was not live")
    _require(_status(evidence_directory / "ready.status") == 503, "corrupt API became ready")
    _require(_status(evidence_directory / "version.status") == 200, "corrupt API version failed")
    _require(_status(evidence_directory / "predict.status") == 503, "corrupt API predicted")
    _require(
        _object(evidence_directory / "ready.json") == {"status": "not_ready"},
        "corrupt readiness body was invalid",
    )
    version = _object(evidence_directory / "version.json")
    _require(version.get("model_ready") is False, "corrupt version claimed model readiness")
    _require(version.get("model_version") is None, "corrupt version exposed a model version")
    _require(version.get("manifest_sha256") is None, "corrupt version exposed a manifest")
    prediction = _object(evidence_directory / "predict.json")
    _require(prediction.get("code") == "model_not_ready", "corrupt prediction error was invalid")
    return {
        "schema_version": "modelguard.local-failure-summary.v1",
        "status": "passed",
        "scenario": "corrupt_bundle",
        "observed": {
            "live": 200,
            "ready": 503,
            "version": 200,
            "model_identity": "absent",
            "prediction": 503,
        },
    }


def validate_sink_outage(evidence_directory: Path) -> dict[str, Any]:
    _require(_status(evidence_directory / "ready.status") == 200, "sink-outage API was not ready")
    _require(_status(evidence_directory / "predict.status") == 200, "sink outage failed closed")
    prediction = _object(evidence_directory / "predict.json")
    _require("risk_score" in prediction, "sink-outage prediction response was invalid")
    metrics = _text(evidence_directory / "metrics.prom")
    _require(
        'modelguard_event_sink_operations_total{outcome="local_failed"} 1.0' in metrics,
        "sink outage was not observable",
    )
    _require(
        'modelguard_errors_total{kind="event_sink"} 1.0' in metrics,
        "sink outage error counter was absent",
    )
    return {
        "schema_version": "modelguard.local-failure-summary.v1",
        "status": "passed",
        "scenario": "sink_outage",
        "observed": {"ready": 200, "prediction": 200, "event_sink": "local_failed"},
    }


def validate_demo(
    healthy_summary_path: Path,
    drifted_summary_path: Path,
    dashboard_health_path: Path,
) -> dict[str, Any]:
    healthy = _object(healthy_summary_path)
    drifted = _object(drifted_summary_path)
    _require(healthy.get("status") == "passed", "healthy demo stage did not pass")
    _require(drifted.get("status") == "passed", "drifted demo stage did not pass")
    _require(healthy.get("scenario") == "baseline", "healthy stage scenario was invalid")
    _require(drifted.get("scenario") == "drifted", "drifted stage scenario was invalid")
    _require(healthy.get("states", {}).get("drift") == "healthy", "healthy state was absent")
    _require(
        drifted.get("states", {}).get("drift") == "degraded",
        "degraded state was absent",
    )
    _require(healthy.get("report_id") != drifted.get("report_id"), "demo report IDs matched")
    _require(_text(dashboard_health_path).strip() == "ok", "final dashboard was unavailable")
    return {
        "schema_version": "modelguard.local-demo-summary.v1",
        "status": "passed",
        "flow": [
            {
                "scenario": "baseline",
                "drift_state": "healthy",
                "report_id": healthy["report_id"],
            },
            {
                "scenario": "drifted",
                "drift_state": "degraded",
                "report_id": drifted["report_id"],
            },
        ],
        "dashboard": "ok",
    }


def validate_e2e(
    insufficient_summary_path: Path,
    corrupt_summary_path: Path,
    sink_summary_path: Path,
) -> dict[str, Any]:
    insufficient = _object(insufficient_summary_path)
    corrupt = _object(corrupt_summary_path)
    sink = _object(sink_summary_path)
    _require(insufficient.get("status") == "passed", "insufficient-data scenario failed")
    _require(
        insufficient.get("states", {}).get("data_quality") == "insufficient_data",
        "insufficient-data state was absent",
    )
    _require(
        insufficient.get("states", {}).get("drift") == "unknown",
        "insufficient-data drift was not unknown",
    )
    _require(corrupt.get("scenario") == "corrupt_bundle", "corrupt-bundle scenario failed")
    _require(sink.get("scenario") == "sink_outage", "sink-outage scenario failed")
    _require(corrupt.get("status") == "passed", "corrupt-bundle evidence did not pass")
    _require(sink.get("status") == "passed", "sink-outage evidence did not pass")
    return {
        "schema_version": "modelguard.local-e2e-summary.v1",
        "status": "passed",
        "scenarios": [
            "insufficient_data",
            "corrupt_bundle",
            "sink_outage",
        ],
    }


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "scenario":
            summary = validate_scenario(
                traffic_path=arguments.traffic,
                monitor_path=arguments.monitor,
                report_path=arguments.report,
                expected_scenario=arguments.expected_scenario,
                expected_accepted=arguments.expected_accepted,
                expected_traffic=arguments.expected_traffic,
                expected_quality=arguments.expected_quality,
                expected_drift=arguments.expected_drift,
            )
        elif arguments.command == "smoke":
            summary = validate_smoke(
                arguments.evidence_dir,
                traffic_events=arguments.traffic_events,
                expected_source_revision=arguments.expected_source_revision,
            )
        elif arguments.command == "corrupt-bundle":
            summary = validate_corrupt_bundle(arguments.evidence_dir)
        elif arguments.command == "sink-outage":
            summary = validate_sink_outage(arguments.evidence_dir)
        elif arguments.command == "demo":
            summary = validate_demo(
                arguments.healthy_summary,
                arguments.drifted_summary,
                arguments.dashboard_health,
            )
        else:
            summary = validate_e2e(
                arguments.insufficient_summary,
                arguments.corrupt_summary,
                arguments.sink_summary,
            )
        _atomic_json(arguments.summary, summary)
    except (EvidenceError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(summary, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
