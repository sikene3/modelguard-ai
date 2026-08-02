"""Typed, side-effect-free configuration for the read-only operations dashboard."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from modelguard.core.config import AppEnvironment


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
    aws_region: str = "us-east-1"
    model_bucket: str | None = None
    report_bucket: str | None = None

    @model_validator(mode="after")
    def validate_repository_boundary(self) -> DashboardSettings:
        if self.app_env is AppEnvironment.AWS and (
            self.dashboard_repository is not DashboardRepositoryMode.S3
        ):
            raise ValueError("AWS dashboard mode requires DASHBOARD_REPOSITORY=s3")
        if self.dashboard_repository is DashboardRepositoryMode.S3 and (
            not self.model_bucket or not self.report_bucket
        ):
            raise ValueError("S3 dashboard mode requires MODEL_BUCKET and REPORT_BUCKET")
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
