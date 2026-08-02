"""Smoke the Streamlit script in honest missing-artifact mode."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def test_dashboard_app_starts_with_missing_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repository_root: Path,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DASHBOARD_REPOSITORY", "local")
    monkeypatch.setenv("LOCAL_REPORT_DIR", str(tmp_path / "missing-reports"))
    monkeypatch.setenv("MODEL_BUNDLE_PATH", str(tmp_path / "missing-model"))
    monkeypatch.setenv(
        "MONITORING_CONFIG_PATH",
        str(repository_root / "configs" / "phase-05-monitoring.json"),
    )
    app_path = repository_root / "src" / "modelguard" / "dashboard" / "app.py"

    app = AppTest.from_file(str(app_path), default_timeout=30).run()

    assert not app.exception
    assert [title.value for title in app.title] == ["ModelGuard AI"]
    assert any("intentionally withheld" in item.value for item in app.info)
