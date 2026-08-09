"""Typed, side-effect-free configuration for the read-only operations dashboard."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from modelguard.core.config import AppEnvironment
from modelguard.monitoring.telemetry import MONITOR_COMPLETION_METRIC_NAME


class DashboardRepositoryMode(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class DashboardSettings(BaseSettings):
    """Dashboard-only settings; loading them never creates an AWS client."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnvironment = AppEnvironment.LOCAL
    dashboard_repository: DashboardRepositoryMode = DashboardRepositoryMode.LOCAL
    local_report_dir: Path = Path("artifacts/reports")
    model_bundle_path: Path = Path("artifacts/model-bundles/1.0.0")
    active_model_version: str = Field(default="1.0.0", pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    monitoring_config_path: Path = Path("configs/phase-05-monitoring.json")
    dashboard_history_limit: int = Field(default=24, ge=2, le=100)
    dashboard_max_json_bytes: int = Field(default=8 * 1024 * 1024, ge=1_024, le=64 * 1024 * 1024)
    dashboard_max_html_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=1_024,
        le=64 * 1024 * 1024,
    )
    dashboard_report_prefix: str = "monitoring/"
    dashboard_model_prefix: str = "model-bundles/"
    dashboard_presigned_url_ttl_seconds: int = Field(default=300, ge=60, le=900)
    dashboard_aws_connect_timeout_seconds: float = Field(default=0.5, gt=0.0, le=5.0)
    dashboard_aws_read_timeout_seconds: float = Field(default=2.0, gt=0.0, le=10.0)
    dashboard_identifier: str = Field(
        default="modelguard-ai-local-operations",
        pattern=r"^[a-z0-9][a-z0-9-]{2,63}$",
    )
    aws_health_required: bool = False
    dashboard_source_region: str | None = None
    dashboard_metric_namespace: str = Field(
        default="ModelGuardAI",
        pattern=r"^[A-Za-z0-9./_-]{1,255}$",
    )
    dashboard_health_metric_name: str = Field(
        default=MONITOR_COMPLETION_METRIC_NAME,
        pattern=r"^[A-Za-z0-9._-]{1,255}$",
    )
    dashboard_monitor_log_group: str | None = None
    dashboard_s3_endpoint_url: str | None = None
    dashboard_cloudwatch_endpoint_url: str | None = None
    dashboard_logs_endpoint_url: str | None = None
    aws_region: str = Field(default="us-east-1", pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-[1-9][0-9]*$")
    model_bucket: str | None = None
    report_bucket: str | None = None

    @model_validator(mode="after")
    def validate_repository_boundary(self) -> DashboardSettings:
        if self.app_env is AppEnvironment.AWS and (
            self.dashboard_repository is not DashboardRepositoryMode.S3
        ):
            raise ValueError("AWS dashboard mode requires DASHBOARD_REPOSITORY=s3")
        if self.app_env is AppEnvironment.AWS and not self.aws_health_required:
            raise ValueError("AWS dashboard mode requires AWS_HEALTH_REQUIRED=true")
        if self.dashboard_repository is DashboardRepositoryMode.S3 and (
            not self.model_bucket or not self.report_bucket
        ):
            raise ValueError("S3 dashboard mode requires MODEL_BUCKET and REPORT_BUCKET")
        if self.aws_health_required:
            if self.app_env is not AppEnvironment.AWS:
                raise ValueError("AWS health probing is allowed only in APP_ENV=aws")
            if self.dashboard_source_region != self.aws_region:
                raise ValueError("DASHBOARD_SOURCE_REGION must exactly match AWS_REGION")
            expected_log_group = "/modelguard-ai/demo/monitor"
            if self.dashboard_monitor_log_group != expected_log_group:
                raise ValueError(
                    "DASHBOARD_MONITOR_LOG_GROUP must identify the exact demo monitor log group"
                )
            if self.dashboard_metric_namespace != "ModelGuardAI":
                raise ValueError("AWS dashboard metric namespace must be ModelGuardAI")
            if self.dashboard_health_metric_name != MONITOR_COMPLETION_METRIC_NAME:
                raise ValueError(
                    f"AWS dashboard health metric must be {MONITOR_COMPLETION_METRIC_NAME}"
                )
            expected_endpoints = {
                "DASHBOARD_S3_ENDPOINT_URL": (
                    self.dashboard_s3_endpoint_url,
                    f"https://s3.{self.aws_region}.amazonaws.com",
                ),
                "DASHBOARD_CLOUDWATCH_ENDPOINT_URL": (
                    self.dashboard_cloudwatch_endpoint_url,
                    f"https://monitoring.{self.aws_region}.amazonaws.com",
                ),
                "DASHBOARD_LOGS_ENDPOINT_URL": (
                    self.dashboard_logs_endpoint_url,
                    f"https://logs.{self.aws_region}.amazonaws.com",
                ),
            }
            for name, (actual, expected) in expected_endpoints.items():
                if actual != expected:
                    raise ValueError(f"{name} must match the exact regional AWS endpoint")
        if (
            self.dashboard_source_region is not None
            and re.fullmatch(
                r"^[a-z]{2}(?:-gov)?-[a-z]+-[1-9][0-9]*$", self.dashboard_source_region
            )
            is None
        ):
            raise ValueError("DASHBOARD_SOURCE_REGION is malformed")
        for name, prefix in (
            ("DASHBOARD_REPORT_PREFIX", self.dashboard_report_prefix),
            ("DASHBOARD_MODEL_PREFIX", self.dashboard_model_prefix),
        ):
            if not prefix or prefix.startswith("/") or not prefix.endswith("/") or ".." in prefix:
                raise ValueError(f"{name} must be a relative non-empty prefix ending in slash")
        return self


def load_dashboard_settings() -> DashboardSettings:
    """Load validated dashboard configuration without reading artifacts or the network."""

    return DashboardSettings()
