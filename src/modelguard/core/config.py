"""Typed application settings with safe local defaults."""

from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """Supported runtime environment names."""

    LOCAL = "local"
    TEST = "test"
    AWS = "aws"


class LogLevel(StrEnum):
    """Supported application log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventSink(StrEnum):
    """Configured prediction-event destination."""

    LOCAL = "local"
    AWS = "aws"
    DISABLED = "disabled"


class ApiAccessMode(StrEnum):
    """Small, explicit API access modes; this is not a general auth platform."""

    LOCAL_OPEN = "local_open"
    HTTPS_BEARER = "https_token"
    HTTP_CIDR_ONLY = "http_cidr_only"


SSM_PARAMETER_ARN_PATTERN = re.compile(
    r"^arn:(?:aws|aws-us-gov|aws-cn):ssm:[a-z0-9-]+:[0-9]{12}:parameter/.+$"
)


class Settings(BaseSettings):
    """Environment-backed settings that are valid in local mode by default."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnvironment = AppEnvironment.LOCAL
    log_level: LogLevel = LogLevel.INFO
    model_bundle_path: Path = Path("artifacts/model-bundles/1.0.0")
    active_model_version: str = "1.0.0"
    model_bundle_trusted_origin: bool = True
    api_access_mode: ApiAccessMode = ApiAccessMode.LOCAL_OPEN
    alb_allowed_cidr: str | None = None
    prediction_token_ssm_arn: str | None = None
    prediction_bearer_token: SecretStr | None = None
    api_max_request_body_bytes: int = Field(default=16_384, ge=1, le=1_048_576)
    api_max_concurrency: int = Field(default=64, ge=1, le=1_024)
    api_inference_workers: int = Field(default=1, ge=1, le=64)
    api_concurrency_wait_timeout_seconds: float = Field(default=1.0, gt=0.0, le=30.0)
    event_sink_timeout_seconds: float = Field(default=0.75, gt=0.0, le=30.0)
    graceful_shutdown_timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    event_sink: EventSink = EventSink.LOCAL
    local_event_dir: Path = Path("artifacts/predictions")
    firehose_connect_timeout_seconds: float = Field(default=0.1, gt=0.0, le=5.0)
    firehose_read_timeout_seconds: float = Field(default=0.2, gt=0.0, le=10.0)
    firehose_max_attempts: int = Field(default=2, ge=1, le=5)
    firehose_retry_base_delay_seconds: float = Field(default=0.025, ge=0.0, le=1.0)
    local_report_dir: Path = Path("artifacts/reports")
    min_monitoring_samples: int = Field(default=500, ge=1)
    aws_region: str = "us-east-1"
    model_bucket: str | None = None
    prediction_bucket: str | None = None
    report_bucket: str | None = None
    firehose_stream_name: str | None = None
    active_model_ssm_parameter: str | None = None
    sns_topic_arn: str | None = None

    @model_validator(mode="after")
    def validate_api_security_boundary(self) -> Settings:
        """Reject ambiguous AWS exposure and secret-delivery configurations."""

        if self.api_inference_workers > self.api_max_concurrency:
            raise ValueError("API_INFERENCE_WORKERS cannot exceed API_MAX_CONCURRENCY")
        if self.app_env is AppEnvironment.AWS:
            if self.api_access_mode is ApiAccessMode.LOCAL_OPEN:
                raise ValueError("AWS deployments cannot use local_open API access")
            if self.alb_allowed_cidr is None:
                raise ValueError("AWS deployments require an explicit ALB_ALLOWED_CIDR")

        if self.alb_allowed_cidr is not None:
            try:
                network = ipaddress.ip_network(self.alb_allowed_cidr, strict=True)
            except ValueError as error:
                raise ValueError("ALB_ALLOWED_CIDR must be a canonical CIDR network") from error
            if network.prefixlen == 0:
                raise ValueError("ALB_ALLOWED_CIDR must not allow the whole internet")

        if self.api_access_mode is ApiAccessMode.HTTPS_BEARER:
            if self.prediction_token_ssm_arn is None or not SSM_PARAMETER_ARN_PATTERN.fullmatch(
                self.prediction_token_ssm_arn
            ):
                raise ValueError("https_token mode requires a valid SSM parameter ARN")
            if self.prediction_bearer_token is None:
                raise ValueError("https_token mode requires an injected bearer token")
            token_length = len(self.prediction_bearer_token.get_secret_value().encode("utf-8"))
            if not 32 <= token_length <= 512:
                raise ValueError("the injected bearer token must contain 32 to 512 UTF-8 bytes")
        elif self.prediction_token_ssm_arn is not None or self.prediction_bearer_token is not None:
            raise ValueError("token settings are allowed only in https_token mode")

        if self.event_sink is EventSink.AWS and not self.firehose_stream_name:
            raise ValueError("EVENT_SINK=aws requires FIREHOSE_STREAM_NAME")
        if self.app_env is AppEnvironment.AWS and self.event_sink is EventSink.LOCAL:
            raise ValueError("AWS deployments cannot use the local prediction-event sink")
        return self


def load_settings() -> Settings:
    """Load validated settings without creating clients or making network calls."""

    return Settings()
