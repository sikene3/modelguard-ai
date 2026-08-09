"""Network-free probes executed inside each production-equivalent runtime image."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _probe_api() -> None:
    from modelguard.core.config import ApiAccessMode, AppEnvironment, EventSink, Settings
    from modelguard.inference.loader import (
        AwsHydratingModelLoader,
        ModelLoadError,
        ModelLoadFailure,
        default_model_loader,
    )

    class InvalidSsm:
        def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]:
            del kwargs
            return {
                "Parameter": {
                    "Name": "/modelguard-ai/demo/models/active",
                    "Type": "String",
                    "Value": "{}",
                    "Version": 1,
                }
            }

    class NoS3:
        def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
            del kwargs
            return {"LocationConstraint": "us-east-1"}

        def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
            del kwargs
            raise AssertionError("invalid SSM pointer must fail before S3")

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env=AppEnvironment.AWS,
        event_sink=EventSink.DISABLED,
        api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
        alb_allowed_cidr="203.0.113.8/32",
        model_bundle_path=Path.home() / "modelguard-runtime-probe/model-bundle",
        active_model_version="1.0.0",
        model_bucket="modelguard-probe-models",
        active_model_ssm_parameter="/modelguard-ai/demo/models/active",
    )
    if not isinstance(default_model_loader(settings), AwsHydratingModelLoader):
        raise RuntimeError("AWS API did not select the hydrating loader")
    loader = AwsHydratingModelLoader(ssm_client=InvalidSsm(), s3_client=NoS3())
    try:
        loader.load(settings)
    except ModelLoadError as error:
        if error.reason is not ModelLoadFailure.HYDRATION_FAILURE:
            raise RuntimeError("AWS API hydration did not fail with a bounded reason") from error
    else:
        raise RuntimeError("AWS API hydration unexpectedly accepted an invalid pointer")
    if settings.model_bundle_path.exists():
        raise RuntimeError("failed AWS API hydration published a partial bundle")


def _probe_dashboard() -> None:
    from modelguard.core.config import AppEnvironment
    from modelguard.dashboard.aws_health import AwsDashboardState, DashboardAwsHealthProbe
    from modelguard.dashboard.config import DashboardRepositoryMode, DashboardSettings

    class S3:
        def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]:
            del kwargs
            return {"LocationConstraint": None}

    class Metrics:
        def list_metrics(self, **kwargs: Any) -> Mapping[str, Any]:
            del kwargs
            return {"Metrics": []}

    class Logs:
        def describe_log_streams(self, **kwargs: Any) -> Mapping[str, Any]:
            del kwargs
            return {
                "logStreams": [
                    {
                        "logStreamName": "ecs/monitor/probe",
                        "lastEventTimestamp": 1,
                    }
                ]
            }

    config_path = Path("/app/configs/phase-05-monitoring.json")
    if not config_path.is_file():
        raise RuntimeError("dashboard image lacks the locked monitoring configuration")
    settings = DashboardSettings(  # type: ignore[call-arg]
        _env_file=None,
        app_env=AppEnvironment.AWS,
        dashboard_repository=DashboardRepositoryMode.S3,
        model_bucket="modelguard-probe-models",
        report_bucket="modelguard-probe-reports",
        aws_health_required=True,
        dashboard_source_region="us-east-1",
        dashboard_monitor_log_group="/modelguard-ai/demo/monitor",
        dashboard_identifier="modelguard-ai-demo-operations",
        dashboard_s3_endpoint_url="https://s3.us-east-1.amazonaws.com",
        dashboard_cloudwatch_endpoint_url="https://monitoring.us-east-1.amazonaws.com",
        dashboard_logs_endpoint_url="https://logs.us-east-1.amazonaws.com",
        monitoring_config_path=config_path,
    )
    result = DashboardAwsHealthProbe(
        settings,
        s3_client=S3(),
        cloudwatch_client=Metrics(),
        logs_client=Logs(),
    ).probe()
    if result.state is not AwsDashboardState.DEGRADED:
        raise RuntimeError("dashboard hid an AWS missing-data source")


def _probe_monitor() -> None:
    from datetime import UTC, datetime

    from modelguard.core.config import Settings
    from modelguard.monitoring.aws_run import AwsRunExitCode, execute_aws_monitoring_once
    from modelguard.monitoring.cli import _parser
    from modelguard.monitoring.config import MonitoringConfig

    config_path = Path("/app/configs/phase-05-monitoring.json")
    if not config_path.is_file():
        raise RuntimeError("monitor image lacks the locked monitoring configuration")
    arguments = _parser().parse_args(
        ["aws-run", "--as-of", "2026-01-01T01:10:00Z", "--window-end", "2026-01-01T01:00:00Z"]
    )
    if arguments.command != "aws-run":
        raise RuntimeError("monitor image lacks the aws-run command")
    result = execute_aws_monitoring_once(
        Settings(_env_file=None),  # type: ignore[call-arg]
        config=MonitoringConfig(),
        as_of=datetime(2026, 1, 1, 1, 10, tzinfo=UTC),
    )
    if result.exit_code is not AwsRunExitCode.INVALID_CONFIGURATION:
        raise RuntimeError("monitor aws-run did not fail closed on missing AWS configuration")


def main() -> int:
    parser = argparse.ArgumentParser(prog="modelguard-runtime-contracts")
    parser.add_argument("component", choices=("api", "dashboard", "monitor"))
    component = parser.parse_args().component
    {"api": _probe_api, "dashboard": _probe_dashboard, "monitor": _probe_monitor}[component]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
