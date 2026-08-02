"""Unit tests for startup loading and the single-bundle predictor."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from modelguard.core.config import AppEnvironment, Settings
from modelguard.inference.loader import ModelLoadError, ModelLoadFailure, VerifiedModelLoader
from modelguard.inference.predictor import Predictor, RiskDecision


def _settings(bundle_path: Path, *, version: str = "1.0.0", trusted: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        model_bundle_path=bundle_path,
        active_model_version=version,
        model_bundle_trusted_origin=trusted,
    )


def test_loader_verifies_bundle_and_predictor_uses_locked_threshold(
    audited_workspace: Any,
    valid_prediction_payload: dict[str, object],
) -> None:
    bundle = VerifiedModelLoader().load(_settings(audited_workspace.result.bundle_path))
    predictor = Predictor(bundle)

    prediction = predictor.predict(valid_prediction_payload)

    assert prediction.risk_score == bundle.smoke_score
    assert prediction.model_version == "1.0.0"
    expected = (
        RiskDecision.HIGH_RISK
        if prediction.risk_score >= bundle.metadata.threshold.threshold
        else RiskDecision.LOW_RISK
    )
    assert prediction.decision is expected


def test_loader_rejects_missing_corrupt_untrusted_and_wrong_version(
    audited_workspace: Any,
    tmp_path: Path,
) -> None:
    loader = VerifiedModelLoader()
    missing = tmp_path / "missing"
    with pytest.raises(ModelLoadError) as missing_error:
        loader.load(_settings(missing))
    assert missing_error.value.reason is ModelLoadFailure.MISSING_BUNDLE

    corrupt = tmp_path / "corrupt"
    shutil.copytree(audited_workspace.result.bundle_path, corrupt)
    (corrupt / "input_schema.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModelLoadError) as corrupt_error:
        loader.load(_settings(corrupt))
    assert corrupt_error.value.reason is ModelLoadFailure.INVALID_BUNDLE

    with pytest.raises(ModelLoadError) as untrusted_error:
        loader.load(_settings(audited_workspace.result.bundle_path, trusted=False))
    assert untrusted_error.value.reason is ModelLoadFailure.INVALID_BUNDLE

    with pytest.raises(ModelLoadError) as version_error:
        loader.load(_settings(audited_workspace.result.bundle_path, version="2.0.0"))
    assert version_error.value.reason is ModelLoadFailure.VERSION_MISMATCH
