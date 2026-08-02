"""Tests for local-first typed settings."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from modelguard.core.config import (
    ApiAccessMode,
    AppEnvironment,
    EventSink,
    LogLevel,
    Settings,
    load_settings,
)


def test_settings_load_local_defaults_without_aws(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings()

    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.log_level is LogLevel.INFO
    assert settings.event_sink is EventSink.LOCAL
    assert settings.api_access_mode is ApiAccessMode.LOCAL_OPEN
    assert settings.api_max_request_body_bytes == 16_384
    assert settings.api_max_concurrency == 64
    assert settings.api_inference_workers == 1
    assert settings.event_sink_timeout_seconds == 0.75
    assert settings.firehose_connect_timeout_seconds == 0.1
    assert settings.firehose_read_timeout_seconds == 0.2
    assert settings.firehose_max_attempts == 2
    assert settings.min_monitoring_samples == 500
    assert settings.aws_region == "us-east-1"
    assert settings.model_bucket is None


def test_settings_load_typed_env_file_values(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "APP_ENV=test\nLOG_LEVEL=DEBUG\nMIN_MONITORING_SAMPLES=750\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.app_env is AppEnvironment.TEST
    assert settings.log_level is LogLevel.DEBUG
    assert settings.min_monitoring_samples == 750


@pytest.mark.parametrize("cidr", [None, "0.0.0.0/0", "::/0", "203.0.113.8/24"])
def test_aws_settings_reject_missing_world_or_noncanonical_cidr(cidr: str | None) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            event_sink=EventSink.DISABLED,
            api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
            alb_allowed_cidr=cidr,
        )


def test_aws_cidr_only_mode_forbids_token_configuration() -> None:
    with pytest.raises(ValidationError, match="token settings"):
        Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            event_sink=EventSink.DISABLED,
            api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
            alb_allowed_cidr="203.0.113.8/32",
            prediction_bearer_token=SecretStr("x" * 32),
        )


def test_https_token_mode_requires_ssm_arn_and_injected_secret() -> None:
    with pytest.raises(ValidationError, match="SSM parameter ARN"):
        Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            event_sink=EventSink.DISABLED,
            api_access_mode=ApiAccessMode.HTTPS_BEARER,
            alb_allowed_cidr="203.0.113.8/32",
            prediction_bearer_token=SecretStr("x" * 32),
        )

    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        event_sink=EventSink.DISABLED,
        api_access_mode=ApiAccessMode.HTTPS_BEARER,
        alb_allowed_cidr="203.0.113.8/32",
        prediction_token_ssm_arn=(
            "arn:aws:ssm:us-east-1:123456789012:parameter/modelguard/demo/predict-token"
        ),
        prediction_bearer_token=SecretStr("correct-horse-battery-staple-1234"),
    )

    assert settings.prediction_bearer_token is not None
    assert "correct-horse" not in repr(settings)


def test_aws_mode_never_allows_local_open_access() -> None:
    with pytest.raises(ValidationError, match="cannot use local_open"):
        Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            event_sink=EventSink.DISABLED,
            api_access_mode=ApiAccessMode.LOCAL_OPEN,
            alb_allowed_cidr="203.0.113.8/32",
        )


def test_inference_workers_cannot_exceed_request_admission_limit() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        Settings(
            _env_file=None,
            api_max_concurrency=1,
            api_inference_workers=2,
        )


def test_event_sink_modes_require_explicit_safe_aws_configuration() -> None:
    with pytest.raises(ValidationError, match="FIREHOSE_STREAM_NAME"):
        Settings(_env_file=None, event_sink=EventSink.AWS)

    with pytest.raises(ValidationError, match="local prediction-event sink"):
        Settings(
            _env_file=None,
            app_env=AppEnvironment.AWS,
            api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
            alb_allowed_cidr="203.0.113.8/32",
            event_sink=EventSink.LOCAL,
        )

    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.AWS,
        api_access_mode=ApiAccessMode.HTTP_CIDR_ONLY,
        alb_allowed_cidr="203.0.113.8/32",
        event_sink=EventSink.AWS,
        firehose_stream_name="modelguard-demo-predictions",
    )
    assert settings.event_sink is EventSink.AWS
    assert settings.firehose_stream_name == "modelguard-demo-predictions"
