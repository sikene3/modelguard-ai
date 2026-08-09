"""Bounded AWS source-health checks that never reinterpret monitoring results."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import Field

from modelguard.core.serialization import StrictArtifactModel
from modelguard.dashboard.config import DashboardSettings


class AwsSourceState(StrEnum):
    HEALTHY = "healthy"
    MISSING_DATA = "missing_data"
    PERMISSION_DENIED = "permission_denied"
    WRONG_REGION = "wrong_region"
    MALFORMED_RESPONSE = "malformed_response"
    UNAVAILABLE = "unavailable"


class AwsDashboardState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AwsSourceHealth(StrictArtifactModel):
    source: str = Field(pattern=r"^(model_bucket|report_bucket|metrics|monitor_logs)$")
    state: AwsSourceState


class AwsDashboardHealth(StrictArtifactModel):
    contract_version: str = "modelguard.dashboard-aws-health.v1"
    dashboard_identifier: str
    region: str
    state: AwsDashboardState
    sources: tuple[AwsSourceHealth, ...]


class S3HealthClient(Protocol):
    def get_bucket_location(self, **kwargs: Any) -> Mapping[str, Any]: ...


class CloudWatchHealthClient(Protocol):
    def list_metrics(self, **kwargs: Any) -> Mapping[str, Any]: ...


class LogsHealthClient(Protocol):
    def describe_log_streams(self, **kwargs: Any) -> Mapping[str, Any]: ...


def _error_state(error: BaseException) -> AwsSourceState:
    if isinstance(error, ClientError):
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
            return AwsSourceState.PERMISSION_DENIED
        if code in {"AuthorizationHeaderMalformed", "PermanentRedirect", "IncorrectEndpoint"}:
            return AwsSourceState.WRONG_REGION
    return AwsSourceState.UNAVAILABLE


def _bucket_region(response: Mapping[str, Any]) -> str:
    if "LocationConstraint" not in response:
        raise ValueError("malformed bucket location response")
    location = response["LocationConstraint"]
    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    if not isinstance(location, str) or not location:
        raise ValueError("malformed bucket location response")
    return location


class DashboardAwsHealthProbe:
    """Check configured source availability; results never alter Phase 05 report states."""

    def __init__(
        self,
        settings: DashboardSettings,
        *,
        s3_client: S3HealthClient | None = None,
        cloudwatch_client: CloudWatchHealthClient | None = None,
        logs_client: LogsHealthClient | None = None,
    ) -> None:
        if not settings.aws_health_required:
            raise ValueError("AWS dashboard health probe requires AWS_HEALTH_REQUIRED=true")
        self._settings = settings
        config = Config(
            connect_timeout=settings.dashboard_aws_connect_timeout_seconds,
            read_timeout=settings.dashboard_aws_read_timeout_seconds,
            retries={"max_attempts": 2, "mode": "standard"},
            user_agent_extra="modelguard-dashboard-health/1",
        )
        # No credential values or profile names are supplied. ECS task-role credentials are resolved
        # by the default SDK provider chain at runtime.
        self._s3 = s3_client or cast(
            S3HealthClient,
            boto3.client(
                "s3",
                region_name=settings.aws_region,
                endpoint_url=settings.dashboard_s3_endpoint_url,
                config=config,
            ),
        )
        self._cloudwatch = cloudwatch_client or cast(
            CloudWatchHealthClient,
            boto3.client(
                "cloudwatch",
                region_name=settings.aws_region,
                endpoint_url=settings.dashboard_cloudwatch_endpoint_url,
                config=config,
            ),
        )
        self._logs = logs_client or cast(
            LogsHealthClient,
            boto3.client(
                "logs",
                region_name=settings.aws_region,
                endpoint_url=settings.dashboard_logs_endpoint_url,
                config=config,
            ),
        )

    def _bucket(self, source: str, bucket: str) -> AwsSourceHealth:
        try:
            response = self._s3.get_bucket_location(Bucket=bucket)
            state = (
                AwsSourceState.HEALTHY
                if _bucket_region(response) == self._settings.aws_region
                else AwsSourceState.WRONG_REGION
            )
        except ValueError:
            state = AwsSourceState.MALFORMED_RESPONSE
        except (BotoCoreError, ClientError, TimeoutError) as error:
            state = _error_state(error)
        return AwsSourceHealth(source=source, state=state)

    def _metrics(self) -> AwsSourceHealth:
        try:
            response = self._cloudwatch.list_metrics(
                Namespace=self._settings.dashboard_metric_namespace,
                MetricName=self._settings.dashboard_health_metric_name,
                Dimensions=[
                    {"Name": "Service", "Value": "monitor"},
                    {"Name": "Environment", "Value": "aws"},
                ],
                RecentlyActive="PT3H",
            )
            metrics = response.get("Metrics")
            if not isinstance(metrics, list):
                state = AwsSourceState.MALFORMED_RESPONSE
            elif not metrics:
                state = AwsSourceState.MISSING_DATA
            else:
                expected_dimensions = {
                    "Service": "monitor",
                    "Environment": "aws",
                }
                exact_identity_found = False
                malformed = False
                for metric in metrics:
                    if not isinstance(metric, Mapping):
                        malformed = True
                        break
                    dimensions = metric.get("Dimensions")
                    if not isinstance(dimensions, list):
                        malformed = True
                        break
                    parsed_dimensions: dict[str, str] = {}
                    for dimension in dimensions:
                        if (
                            not isinstance(dimension, Mapping)
                            or not isinstance(dimension.get("Name"), str)
                            or not isinstance(dimension.get("Value"), str)
                            or dimension["Name"] in parsed_dimensions
                        ):
                            malformed = True
                            break
                        parsed_dimensions[dimension["Name"]] = dimension["Value"]
                    if malformed:
                        break
                    if (
                        metric.get("Namespace") == self._settings.dashboard_metric_namespace
                        and metric.get("MetricName") == self._settings.dashboard_health_metric_name
                        and parsed_dimensions == expected_dimensions
                    ):
                        exact_identity_found = True
                state = (
                    AwsSourceState.HEALTHY
                    if exact_identity_found and not malformed
                    else AwsSourceState.MALFORMED_RESPONSE
                )
        except (BotoCoreError, ClientError, TimeoutError) as error:
            state = _error_state(error)
        return AwsSourceHealth(source="metrics", state=state)

    def _monitor_logs(self) -> AwsSourceHealth:
        try:
            response = self._logs.describe_log_streams(
                logGroupName=self._settings.dashboard_monitor_log_group,
                orderBy="LastEventTime",
                descending=True,
                limit=1,
            )
            streams = response.get("logStreams")
            if not isinstance(streams, list):
                state = AwsSourceState.MALFORMED_RESPONSE
            elif not streams:
                state = AwsSourceState.MISSING_DATA
            else:
                stream = streams[0]
                if (
                    not isinstance(stream, Mapping)
                    or not isinstance(stream.get("logStreamName"), str)
                    or not stream["logStreamName"]
                    or not isinstance(stream.get("lastEventTimestamp"), int)
                    or stream["lastEventTimestamp"] < 0
                ):
                    state = AwsSourceState.MALFORMED_RESPONSE
                else:
                    state = AwsSourceState.HEALTHY
        except (BotoCoreError, ClientError, TimeoutError) as error:
            state = _error_state(error)
        return AwsSourceHealth(source="monitor_logs", state=state)

    def probe(self) -> AwsDashboardHealth:
        if self._settings.model_bucket is None or self._settings.report_bucket is None:
            raise ValueError("AWS dashboard buckets were not validated")
        sources = (
            self._bucket("model_bucket", self._settings.model_bucket),
            self._bucket("report_bucket", self._settings.report_bucket),
            self._metrics(),
            self._monitor_logs(),
        )
        healthy_count = sum(source.state is AwsSourceState.HEALTHY for source in sources)
        if healthy_count == len(sources):
            state = AwsDashboardState.HEALTHY
        elif healthy_count == 0 and all(
            source.state is not AwsSourceState.MISSING_DATA for source in sources
        ):
            state = AwsDashboardState.UNAVAILABLE
        else:
            state = AwsDashboardState.DEGRADED
        return AwsDashboardHealth(
            dashboard_identifier=self._settings.dashboard_identifier,
            region=self._settings.aws_region,
            state=state,
            sources=sources,
        )
