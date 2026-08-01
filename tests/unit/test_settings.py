"""Tests for local-first typed settings."""

from pathlib import Path

from pytest import MonkeyPatch

from modelguard.core.config import AppEnvironment, EventSink, LogLevel, load_settings


def test_settings_load_local_defaults_without_aws(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings()

    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.log_level is LogLevel.INFO
    assert settings.event_sink is EventSink.LOCAL
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
