"""Typed application settings with safe local defaults."""

from enum import StrEnum
from pathlib import Path

from pydantic import Field
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
    FIREHOSE = "firehose"


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
    event_sink: EventSink = EventSink.LOCAL
    local_event_dir: Path = Path("artifacts/predictions")
    local_report_dir: Path = Path("artifacts/reports")
    min_monitoring_samples: int = Field(default=500, ge=1)
    aws_region: str = "us-east-1"
    model_bucket: str | None = None
    prediction_bucket: str | None = None
    report_bucket: str | None = None
    firehose_stream_name: str | None = None
    active_model_ssm_parameter: str | None = None
    sns_topic_arn: str | None = None


def load_settings() -> Settings:
    """Load validated settings without creating clients or making network calls."""

    return Settings()
