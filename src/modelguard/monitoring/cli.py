"""Phase 05 deterministic monitoring command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from modelguard.core.config import Settings, load_settings
from modelguard.monitoring.config import MonitoringConfig, load_monitoring_config
from modelguard.monitoring.events import (
    EventIdentity,
    parse_utc_timestamp,
    target_identity_from_bundle,
)
from modelguard.monitoring.persistence import LocalRunStateStore
from modelguard.monitoring.service import LocalMonitoringRunSpec, run_local_monitoring
from modelguard.training.bundle import inspect_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="modelguard-monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="finalize one deterministic monitoring window")
    run_parser.add_argument("--window-end", help="UTC window end ending in Z; defaults by as-of")
    run_parser.add_argument(
        "--as-of", required=True, help="explicit UTC finalization time ending in Z"
    )
    run_parser.add_argument("--bundle", type=Path)
    run_parser.add_argument("--config", type=Path, default=Path("configs/phase-05-monitoring.json"))
    run_parser.add_argument("--event-dir", type=Path)
    run_parser.add_argument("--report-dir", type=Path)
    run_parser.add_argument("--label-dir", type=Path)
    run_parser.add_argument("--known-bundle", action="append", type=Path, default=[])
    run_parser.add_argument("--minimum-accepted-events", type=int)
    run_parser.add_argument("--target-event-schema-version")
    run_parser.add_argument("--target-model-version")
    run_parser.add_argument("--target-manifest-sha256")
    run_parser.add_argument("--target-input-schema-version")

    status_parser = subparsers.add_parser("status", help="derive run health without changing state")
    status_parser.add_argument(
        "--as-of", required=True, help="explicit UTC observation time ending in Z"
    )
    status_parser.add_argument("--report-dir", type=Path)
    return parser


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True))


def _resolve_target(args: argparse.Namespace, bundle_path: Path) -> EventIdentity:
    explicit_values = (
        args.target_event_schema_version,
        args.target_model_version,
        args.target_manifest_sha256,
        args.target_input_schema_version,
    )
    if any(value is not None for value in explicit_values):
        if any(value is None for value in explicit_values):
            raise ValueError("all four explicit target identity arguments are required together")
        return EventIdentity(
            event_schema_version=args.target_event_schema_version,
            model_version=args.target_model_version,
            bundle_manifest_sha256=args.target_manifest_sha256,
            input_schema_version=args.target_input_schema_version,
        )
    # The validation quickstart intentionally permits this convenience. The fully resolved identity
    # is still frozen before the raw monitoring run and verified again inside the service.
    return target_identity_from_bundle(inspect_bundle(bundle_path))


def _run(args: argparse.Namespace, settings: Settings) -> int:
    bundle_path = args.bundle or settings.model_bundle_path
    event_directory = args.event_dir or settings.local_event_dir
    report_directory = args.report_dir or settings.local_report_dir
    as_of = parse_utc_timestamp(args.as_of, name="as_of")
    window_end = (
        parse_utc_timestamp(args.window_end, name="window_end")
        if args.window_end is not None
        else None
    )
    status_store = LocalRunStateStore(report_directory)
    try:
        config = load_monitoring_config(args.config)
        requested_minimum = (
            args.minimum_accepted_events
            if args.minimum_accepted_events is not None
            else settings.min_monitoring_samples
        )
        if requested_minimum != config.minimum_accepted_events:
            config = MonitoringConfig.model_validate(
                {
                    **config.model_dump(mode="python"),
                    "minimum_accepted_events": requested_minimum,
                }
            )
        target = _resolve_target(args, bundle_path)
        result = run_local_monitoring(
            LocalMonitoringRunSpec(
                bundle_path=bundle_path,
                event_directory=event_directory,
                report_directory=report_directory,
                target_identity=target,
                known_non_target_bundle_paths=args.known_bundle,
                label_directory=args.label_dir,
                window_end=window_end,
                as_of=as_of,
                environment=settings.app_env,
            ),
            config=config,
            run_state_store=status_store,
        )
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, OSError):
            category = "storage_failure"
        elif isinstance(error, ValueError):
            category = "invalid_monitoring_contract"
        else:
            category = "monitoring_runtime_failure"
        try:
            status_store.record_failure(attempted_at=as_of, reason=category)
        except OSError:
            print("error: monitor failed and run-status persistence also failed", file=sys.stderr)
        print(f"error: {category}", file=sys.stderr)
        return 1
    report = result.report
    counts = report.records.counts
    _print_json(
        {
            "accepted_target": counts.accepted_target,
            "data_quality_state": report.states.data_quality.value,
            "drift_state": report.states.drift.value,
            "html_report": str(result.published.html_path),
            "html_sha256": result.published.html_sha256,
            "json_report": str(result.published.json_path),
            "json_sha256": result.published.json_sha256,
            "latest_updated": result.published.latest_updated,
            "performance_state": report.states.performance.value,
            "report_id": report.report_id,
            "run_state": report.states.run.value,
        }
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run or inspect persistent monitoring state using explicit observation time."""

    args = _parser().parse_args(argv)
    settings = load_settings()
    if args.command == "run":
        return _run(args, settings)
    as_of = parse_utc_timestamp(args.as_of, name="as_of")
    report_directory = args.report_dir or settings.local_report_dir
    config = MonitoringConfig(minimum_accepted_events=settings.min_monitoring_samples)
    state = LocalRunStateStore(report_directory).state_as_of(as_of=as_of, config=config)
    _print_json({"as_of": args.as_of, "run_state": state.value})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
